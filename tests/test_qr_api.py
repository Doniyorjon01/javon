"""QR codes, the A4 poster and shelf labels."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from services import qr
from tests.factories import make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


async def test_store_and_book_qr_codes(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    item = await make_item(tenant, await make_book(db, "O'tkan kunlar"))
    await sign_in(client, owner)

    svg = await client.get(f"/tenants/{tenant.id}/qr/store")
    assert svg.status_code == 200
    assert svg.headers["content-type"] == "image/svg+xml"
    assert svg.content == qr.qr_svg("https://varaq.javon.uz/?src=qr")

    png = await client.get(f"/tenants/{tenant.id}/qr/store", params={"format": "png"})
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")

    book = await client.get(f"/tenants/{tenant.id}/qr/items/{item.id}")
    assert book.content == qr.qr_svg(f"https://varaq.javon.uz/kitob/{item.book_id}?src=qr")
    assert (await client.get(f"/tenants/{tenant.id}/qr/store", params={"format": "gif"})).status_code == 422


async def test_another_stores_item_is_not_found(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    other = await make_tenant(db, "kitobxon")
    foreign = await make_item(other, await make_book(db))
    await sign_in(client, owner)
    assert (await client.get(f"/tenants/{tenant.id}/qr/items/{foreign.id}")).status_code == 404
    resp = await client.get(f"/tenants/{tenant.id}/qr/labels.pdf", params={"items": str(foreign.id)})
    assert resp.status_code == 404
    assert (await client.get(f"/tenants/{other.id}/qr/store")).status_code == 404


async def test_labels_and_poster(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    kunlar = await make_item(
        tenant, await make_book(db, "O'tkan kunlar", ["Abdulla Qodiriy"]), price=4_500_000
    )
    chayon = await make_item(tenant, await make_book(db, "Mehrobdan chayon"), price=3_000_000)
    await make_item(tenant, await make_book(db, "Yashirin kitob"), is_visible=False)
    await sign_in(client, owner)

    sheet = await client.get(f"/tenants/{tenant.id}/qr/labels.pdf")
    assert sheet.status_code == 200
    assert sheet.headers["content-type"] == "application/pdf"
    assert sheet.content.startswith(b"%PDF")
    assert pages(sheet.content) == 1

    # 25 labels (an id repeated = copies) need two A4 sheets of 24.
    ids = ",".join([str(kunlar.id)] * 20 + [str(chayon.id)] * 5)
    many = await client.get(f"/tenants/{tenant.id}/qr/labels.pdf", params={"items": ids})
    assert many.status_code == 200
    assert pages(many.content) == 2

    for bad in ("1,x", ",".join(["1"] * (qr.MAX_LABELS + 1)), "0"):
        resp = await client.get(f"/tenants/{tenant.id}/qr/labels.pdf", params={"items": bad})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "label_items_invalid"

    poster = await client.get(f"/tenants/{tenant.id}/qr/poster.pdf")
    assert poster.status_code == 200 and poster.content.startswith(b"%PDF")
    if qr.fonts().unicode:  # DejaVu installed: Cyrillic and Uzbek letters print
        assert b"DejaVuSans" in poster.content


def test_label_layout_fills_a4() -> None:
    assert qr.LABEL_COLUMNS * qr.LABEL_ROWS == 24
    assert round(qr.LABEL_W / qr.mm) == 70
    body = qr.labels_pdf(
        [qr.Label("https://a.javon.uz/kitob/1?src=qr", "Сарлавҳа " * 12, "Muallif", 1_234_500)] * 3,
        "Doʻkon",
        qr.Lang.ru,
    )
    assert body.startswith(b"%PDF")
