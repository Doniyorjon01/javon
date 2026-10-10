"""
Stores — platform side
======================
GET /tenants/slug-check   wizard step "Do'kon nomi": as the owner types the name,
                          the frontend shows the suggested address and whether it
                          is free. Public on purpose: whether varaq.javon.uz exists
                          is public anyway.

Creating and editing a store needs a signed-in owner; those routes arrive with
authentication in step 3 (db_tenant.create_tenant / update_tenant are ready).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_tenant
from database.config import get_pg_db
from errors import generate_error
from schemas.tenant import SlugCheckOut
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