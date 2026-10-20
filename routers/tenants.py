"""
Stores — the owner's side
=========================
GET   /tenants/slug-check   wizard step "Do'kon nomi": as the owner types the name,
                            the frontend shows the suggested address and whether it
                            is free. Public on purpose: whether varaq.javon.uz exists
                            is public anyway.
POST  /tenants              create a store; the caller becomes its owner (at most
                            users.max_stores stores per account, 1 by default)
GET   /tenants/{tenant_id}  the store's settings — owner and staff
PATCH /tenants/{tenant_id}  change look and contacts — owner only
POST  /tenants/{tenant_id}/launch
                            last wizard step: the storefront becomes public — owner
                            only; needs at least one book on sale (409
                            launch_needs_books); calling it again changes nothing
POST  /tenants/{tenant_id}/pause    owner: close the storefront for a while (holiday,
                                   stocktake); the admin panel keeps working
POST  /tenants/{tenant_id}/resume   owner: open it again
DELETE /tenants/{tenant_id}         owner, {"confirm_slug": "<slug>"}: close the store
                                   for good (soft delete); refused while orders are
                                   unfinished; the Telegram bot is disconnected
PUT   /tenants/{tenant_id}/logo
                            multipart "file": JPEG, PNG or WebP up to MAX_UPLOAD_BYTES;
                            stored as WebP variants (TenantOut.logo) — owner only
DELETE /tenants/{tenant_id}/logo

The store comes from the path through get_current_member / get_current_owner,
which also bind the DB session to it (RLS). Never read tenant_id from a body.
"""

import logging

from fastapi import APIRouter, Depends, File, Query, Request, Security, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member, get_current_owner, get_current_user
from config import settings
from database import db_telegram, db_tenant
from database.config import get_pg_db
from errors import generate_error
from models.tenant import Tenant
from models.user import User
from schemas.tenant import SlugCheckOut, TenantCreate, TenantDeleteIn, TenantOut, TenantUpdate
from services.media import read_upload
from services.storage import Storage, get_storage
from services.telegram import TelegramClient
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.slug import slugify

router = APIRouter(prefix="/tenants", tags=["tenants"])
logger = logging.getLogger(__name__)


def get_telegram(request: Request) -> TelegramClient:
    return request.app.state.telegram


@router.get("/slug-check", response_model=SlugCheckOut)
async def slug_check(
    name: str | None = Query(default=None, max_length=80, description="Store name; a slug is derived"),
    slug: str | None = Query(default=None, max_length=60, description="Exact slug the owner typed"),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> SlugCheckOut:
    candidate = slug.strip().lower() if slug else slugify(name or "")
    if not candidate:
        raise generate_error(Msg.SLUG_CHECK_EMPTY, lang)
    return await db_tenant.check_slug(db, candidate)


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.create_tenant(db, user.id, data, lang)


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.get_tenant(db, member.tenant_id, lang)


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    data: TenantUpdate,
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.update_tenant(db, owner.tenant_id, data, lang)


@router.post("/{tenant_id}/launch", response_model=TenantOut)
async def launch_tenant(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.launch_tenant(db, owner.tenant_id, lang)


@router.put("/{tenant_id}/logo", response_model=TenantOut)
async def upload_logo(
    file: UploadFile = File(description="JPEG, PNG or WebP"),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_storage),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    data = await read_upload(file, settings.MAX_UPLOAD_BYTES, lang)
    return await db_tenant.set_logo(db, storage, owner.tenant_id, data, lang)


@router.delete("/{tenant_id}/logo", response_model=TenantOut)
async def delete_logo(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_storage),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.delete_logo(db, storage, owner.tenant_id, lang)


@router.post("/{tenant_id}/pause", response_model=TenantOut)
async def pause_tenant(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.set_paused(db, owner.tenant_id, True, lang)


@router.post("/{tenant_id}/resume", response_model=TenantOut)
async def resume_tenant(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    return await db_tenant.set_paused(db, owner.tenant_id, False, lang)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    data: TenantDeleteIn,
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    client: TelegramClient = Depends(get_telegram),
    lang: Lang = Depends(get_lang),
) -> None:
    tenant_id = owner.tenant_id
    await db_tenant.delete_tenant(db, tenant_id, data.confirm_slug, lang)
    # A deleted store's bot must stop answering buyers. Best effort: the store is
    # already gone, a Telegram hiccup must not undo that.
    if await db_telegram.get_bot(db, tenant_id) is not None:
        try:
            await db_telegram.disconnect_bot(db, client, tenant_id, lang)
        except Exception:
            logger.warning("Bot of a deleted store not disconnected", extra={"tenant_id": tenant_id})
