"""
QR codes and printables (owner and staff)
=========================================
GET /tenants/{tenant_id}/qr/store?format=svg|png        the store's site
GET /tenants/{tenant_id}/qr/items/{item_id}?format=     one book's page in the store
GET /tenants/{tenant_id}/qr/poster.pdf                  A4 poster for the door or the till
GET /tenants/{tenant_id}/qr/labels.pdf?items=3,3,8      A4 sticker sheets, 3 x 8 labels:
                                                        QR, title, author, price. Repeat an id
                                                        for more copies; no ids = every book
                                                        on sale, by title. At most 240 labels.

Links point at STOREFRONT_URL_TEMPLATE (book pages at /kitob/<book id>) with
?src=qr. The store's site address never changes (slugs are permanent), so
printed codes stay valid.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member
from database import db_inventory, db_tenant
from database.config import get_pg_db
from errors import generate_error
from schemas.base import BIGINT_MAX
from services import qr
from translations import Msg
from utils.i18n import Lang, get_lang

router = APIRouter(prefix="/tenants/{tenant_id}/qr", tags=["qr"])

ImageFormat = Literal["svg", "png"]
_MEDIA = {"svg": "image/svg+xml", "png": "image/png"}
# Printables change only when the shelf does; a short private cache is enough.
_CACHE = {"Cache-Control": "private, max-age=300"}


def _image(data: str, image_format: ImageFormat, name: str) -> Response:
    body = qr.qr_svg(data) if image_format == "svg" else qr.qr_png(data)
    return Response(
        body,
        media_type=_MEDIA[image_format],
        headers={**_CACHE, "Content-Disposition": f'inline; filename="{name}.{image_format}"'},
    )


def _pdf(body: bytes, name: str) -> Response:
    return Response(
        body,
        media_type="application/pdf",
        headers={**_CACHE, "Content-Disposition": f'inline; filename="{name}.pdf"'},
    )


def _store_lang(languages: list[str]) -> Lang:
    first = languages[0] if languages else "uz"
    return Lang(first) if first in Lang.__members__ else Lang.uz


@router.get("/store")
async def store_qr(
    image_format: ImageFormat = Query(default="svg", alias="format"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Response:
    tenant = await db_tenant.get_tenant(db, member.tenant_id, lang)
    return _image(qr.tracked(qr.store_url(tenant.slug)), image_format, f"{tenant.slug}-qr")


@router.get("/items/{item_id}")
async def item_qr(
    item_id: int = Path(gt=0, le=BIGINT_MAX),
    image_format: ImageFormat = Query(default="svg", alias="format"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Response:
    tenant = await db_tenant.get_tenant(db, member.tenant_id, lang)
    item = await db_inventory.get_item(db, member.tenant_id, item_id, lang)
    url = qr.tracked(qr.book_url(tenant.slug, item.book_id))
    return _image(url, image_format, f"{tenant.slug}-kitob-{item.book_id}")


@router.get("/poster.pdf")
async def poster(
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Response:
    tenant = await db_tenant.get_tenant(db, member.tenant_id, lang)
    url = qr.tracked(qr.store_url(tenant.slug))
    body = await asyncio.to_thread(qr.poster_pdf, tenant.name, url, _store_lang(tenant.languages))
    return _pdf(body, f"{tenant.slug}-poster")


def _parse_ids(raw: str | None, lang: Lang) -> list[int] | None:
    if raw is None or not raw.strip():
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) > qr.MAX_LABELS or not all(
        part.isdigit() and 0 < int(part) <= BIGINT_MAX for part in parts
    ):
        raise generate_error(Msg.LABEL_ITEMS_INVALID, lang, format_values=(qr.MAX_LABELS,))
    return [int(part) for part in parts]


@router.get("/labels.pdf")
async def labels(
    items: str | None = Query(default=None, max_length=5000, description="Comma-separated item ids"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Response:
    item_ids = _parse_ids(items, lang)
    tenant = await db_tenant.get_tenant(db, member.tenant_id, lang)
    rows = await db_inventory.get_label_items(db, member.tenant_id, item_ids, qr.MAX_LABELS, lang)
    if not rows:
        raise generate_error(Msg.LABEL_ITEMS_INVALID, lang, format_values=(qr.MAX_LABELS,))
    store_lang = _store_lang(tenant.languages)
    entries = [
        qr.Label(
            url=qr.tracked(qr.book_url(tenant.slug, item.book_id)),
            title=item.book.title,
            authors=", ".join(author.name for author in item.book.authors),
            price=item.price,
        )
        for item in rows
    ]
    body = await asyncio.to_thread(qr.labels_pdf, entries, tenant.name, store_lang)
    return _pdf(body, f"{tenant.slug}-yorliqlar")
