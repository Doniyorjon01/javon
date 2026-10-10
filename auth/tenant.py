"""
Tenant context dependencies
===========================
A route gets "which store is this request for" from a dependency here, never
from its own parameters. The dependency also binds the request's DB session to
that store, so Row Level Security applies to everything the route reads or writes.

Storefront: the store is addressed by slug in the path, /storefront/{slug}/...
The Next.js frontend maps varaq.javon.uz (and later custom domains) to that path,
so the API never has to trust a Host header.

FastAPI caches dependencies per request: the `db` a route receives from
get_pg_db is the same session bound here.
"""

from fastapi import Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_tenant
from database.config import bind_tenant, get_pg_db
from models.tenant import Tenant
from utils.i18n import Lang, get_lang
from utils.slug import SLUG_MAX_LENGTH


async def get_storefront_tenant(
    slug: str = Path(min_length=1, max_length=SLUG_MAX_LENGTH),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    tenant = await db_tenant.get_storefront_tenant(db, slug.lower(), lang)
    await bind_tenant(db, tenant.id)
    return tenant