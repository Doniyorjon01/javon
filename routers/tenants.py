"""
Stores — the owner's side
=========================
GET   /tenants/slug-check   wizard step "Do'kon nomi": as the owner types the name,
                            the frontend shows the suggested address and whether it
                            is free. Public on purpose: whether varaq.javon.uz exists
                            is public anyway.
POST  /tenants              create a store; the caller becomes its owner
GET   /tenants/{tenant_id}  the store's settings — owner and staff
PATCH /tenants/{tenant_id}  change look and contacts — owner only

The store comes from the path through get_current_member / get_current_owner,
which also bind the DB session to it (RLS). Never read tenant_id from a body.
"""

from fastapi import APIRouter, Depends, Query, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member, get_current_owner, get_current_user
from database import db_tenant
from database.config import get_pg_db
from errors import generate_error
from models.tenant import Tenant
from models.user import User
from schemas.tenant import SlugCheckOut, TenantCreate, TenantOut, TenantUpdate
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.slug import slugify

router = APIRouter(prefix="/tenants", tags=["tenants"])


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
