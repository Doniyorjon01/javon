"""
Storefront API — public, what buyers see
========================================
Everything under /storefront/{slug} is scoped to one store by
get_storefront_tenant: a store that is not launched, suspended or deleted
answers 404 everywhere. No sign-in; prices in tiyin.

GET  /storefront/{slug}                         the store: name, look, contacts, delivery
GET  /storefront/{slug}/books?q=&language=&script=&author_id=&publisher_id=
                             &min_price=&max_price=&in_stock=&sort=
                                                the shelf: search and filters
GET  /storefront/{slug}/books/{book_id}         a book page, with similar books
GET  /storefront/{slug}/facets                  what the filter panel can offer
GET  /storefront/{slug}/sitemap                 book ids and dates for sitemap.xml
POST /storefront/{slug}/orders                  place an order (routers/orders.py)
GET  /storefront/{slug}/orders/{order_id}?token=  track it
"""

from fastapi import APIRouter, Depends, Path, Query
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from auth.tenant import get_storefront_tenant
from database import db_storefront
from database.config import get_pg_db
from models.catalog import BookLanguage, BookScript
from models.inventory import MAX_PRICE
from models.tenant import Tenant
from schemas.base import BIGINT_MAX
from schemas.storefront import (
    FacetsOut,
    SitemapEntry,
    StorefrontItemOut,
    StorefrontItemPageOut,
    StorefrontSort,
)
from schemas.tenant import StorefrontOut
from utils.i18n import Lang, get_lang
from utils.pagination import CustomPage

router = APIRouter(prefix="/storefront/{slug}", tags=["storefront"])


@router.get("", response_model=StorefrontOut)
async def get_store(tenant: Tenant = Depends(get_storefront_tenant)) -> Tenant:
    return tenant


@router.get("/books", response_model=CustomPage[StorefrontItemOut])
async def get_books(
    q: str | None = Query(default=None, max_length=100, description="Title, author, publisher or ISBN"),
    language: BookLanguage | None = None,
    script: BookScript | None = None,
    author_id: int | None = Query(default=None, gt=0, le=BIGINT_MAX),
    publisher_id: int | None = Query(default=None, gt=0, le=BIGINT_MAX),
    min_price: int | None = Query(default=None, ge=0, le=MAX_PRICE, description="tiyin"),
    max_price: int | None = Query(default=None, ge=0, le=MAX_PRICE, description="tiyin"),
    in_stock: bool | None = None,
    sort: StorefrontSort | None = Query(default=None, description="default: relevance with q, else new"),
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> object:
    stmt = db_storefront.get_items(
        tenant.id,
        query=q,
        language=language,
        script=script,
        author_id=author_id,
        publisher_id=publisher_id,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        sort=sort,
        lang=lang,
    )
    return await apaginate(db, stmt)


@router.get("/books/{book_id}", response_model=StorefrontItemPageOut)
async def get_book(
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> StorefrontItemPageOut:
    item = await db_storefront.get_item(db, tenant.id, book_id, lang)
    similar = await db_storefront.get_similar(db, tenant.id, item)
    page = StorefrontItemPageOut.model_validate(item)
    page.similar = [StorefrontItemOut.model_validate(other) for other in similar]
    return page


@router.get("/facets", response_model=FacetsOut)
async def get_facets(
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
) -> FacetsOut:
    return await db_storefront.get_facets(db, tenant.id)


@router.get("/sitemap", response_model=list[SitemapEntry])
async def get_sitemap(
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
) -> list[SitemapEntry]:
    return await db_storefront.get_sitemap(db, tenant.id)
