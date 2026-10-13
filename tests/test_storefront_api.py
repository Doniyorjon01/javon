"""The public storefront: what buyers can see, find and filter."""

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Book, BookStatus, Tenant
from tests.factories import make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


async def titles(client: AsyncClient, slug: str = "varaq", **params: object) -> list[str]:
    resp = await client.get(f"/storefront/{slug}/books", params=params)
    assert resp.status_code == 200, resp.text
    return [row["book"]["title"] for row in resp.json()["items"]]


@pytest.fixture
async def shop(db: AsyncSession) -> Tenant:
    """A store with a small shelf of different books."""
    tenant = await make_tenant(db, "varaq")
    qodiriy = ["Abdulla Qodiriy"]
    await make_item(
        tenant, await make_book(db, "O'tkan kunlar", qodiriy, publisher="Sharq"), price=4_500_000, quantity=3
    )
    await make_item(tenant, await make_book(db, "Mehrobdan chayon", qodiriy), price=3_900_000, quantity=0)
    await make_item(
        tenant,
        await make_book(db, "Преступление и наказание", ["Фёдор Достоевский"], language="ru"),
        price=6_000_000,
        quantity=1,
    )
    await make_item(
        tenant, await make_book(db, "Sharq yulduzi", ["Kimdir"], publisher="Sharq"), price=2_000_000
    )
    await make_item(tenant, await make_book(db, "Yashirin kitob"), is_visible=False)
    return tenant


async def test_only_visible_books_of_this_store(client: AsyncClient, db: AsyncSession, shop: Tenant) -> None:
    other = await make_tenant(db, "boshqa")
    await make_item(other, await make_book(db, "Boshqa doʻkonniki"))
    shown = await titles(client)
    assert "Yashirin kitob" not in shown and "Boshqa doʻkonniki" not in shown
    assert len(shown) == 4

    # A book the platform later rejects disappears from shelves.
    await db.execute(update(Book).where(Book.title == "Sharq yulduzi").values(status=BookStatus.REJECTED))
    await db.commit()
    assert "Sharq yulduzi" not in await titles(client)


async def test_cards_show_in_stock_not_quantities(client: AsyncClient, shop: Tenant) -> None:
    rows = (await client.get("/storefront/varaq/books", params={"sort": "title"})).json()["items"]
    first = rows[0]
    assert set(first) == {"book", "price", "in_stock"}
    assert {r["book"]["title"]: r["in_stock"] for r in rows}["Mehrobdan chayon"] is False
    assert "status" not in first["book"] and "mxik_code" not in first["book"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "Қодирий", "sort": "title"}, ["Mehrobdan chayon", "O'tkan kunlar"]),
        ({"q": "prestuplenie"}, ["Преступление и наказание"]),
        ({"language": "ru"}, ["Преступление и наказание"]),
        ({"script": "cyrl"}, ["Преступление и наказание"]),
        (
            {"in_stock": True, "sort": "price_asc"},
            ["Sharq yulduzi", "O'tkan kunlar", "Преступление и наказание"],
        ),
        ({"min_price": 4_000_000, "max_price": 5_000_000}, ["O'tkan kunlar"]),
        (
            {"sort": "price_desc"},
            ["Преступление и наказание", "O'tkan kunlar", "Mehrobdan chayon", "Sharq yulduzi"],
        ),
    ],
)
async def test_search_filters_and_sorting(
    client: AsyncClient, shop: Tenant, params: dict, expected: list[str]
) -> None:
    assert await titles(client, **params) == expected


async def test_filter_by_author_and_publisher(client: AsyncClient, shop: Tenant) -> None:
    facets = (await client.get("/storefront/varaq/facets")).json()
    qodiriy = next(a for a in facets["authors"] if a["name"] == "Abdulla Qodiriy")
    sharq = next(p for p in facets["publishers"] if p["name"] == "Sharq")
    assert qodiriy["count"] == 2 and sharq["count"] == 2
    assert sorted(await titles(client, author_id=qodiriy["id"])) == ["Mehrobdan chayon", "O'tkan kunlar"]
    assert sorted(await titles(client, publisher_id=sharq["id"])) == ["O'tkan kunlar", "Sharq yulduzi"]
    assert facets["total"] == 4
    assert (facets["price_min"], facets["price_max"]) == (2_000_000, 6_000_000)
    assert {v["value"]: v["count"] for v in facets["languages"]} == {"uz": 3, "ru": 1}


async def test_book_page_with_similar_books(client: AsyncClient, shop: Tenant) -> None:
    rows = (await client.get("/storefront/varaq/books", params={"q": "otkan kunlar"})).json()["items"]
    book_id = rows[0]["book"]["id"]
    page = (await client.get(f"/storefront/varaq/books/{book_id}")).json()
    assert page["book"]["title"] == "O'tkan kunlar"
    assert page["price"] == 4_500_000 and page["in_stock"] is True
    # Same author first, then same publisher.
    assert [s["book"]["title"] for s in page["similar"]] == ["Mehrobdan chayon", "Sharq yulduzi"]


async def test_hidden_or_foreign_book_page_is_404(
    client: AsyncClient, db: AsyncSession, shop: Tenant
) -> None:
    hidden = (await make_book(db, "Boshqa kitob")).id
    assert (await client.get(f"/storefront/varaq/books/{hidden}")).status_code == 404


async def test_sitemap_lists_every_listed_book(client: AsyncClient, shop: Tenant) -> None:
    entries = (await client.get("/storefront/varaq/sitemap")).json()
    assert len(entries) == 4
    assert set(entries[0]) == {"book_id", "updated_at"}


async def test_unlaunched_store_has_no_storefront(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "yangi", launched=False)
    await make_item(tenant, await make_book(db))
    assert (await client.get("/storefront/yangi/books")).status_code == 404
    assert (await client.get("/storefront/yangi/facets")).status_code == 404


async def test_delivery_settings_are_public(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    changed = await client.patch(
        f"/tenants/{tenant.id}",
        json={"delivery_enabled": True, "delivery_fee": 1_500_000, "free_delivery_from": 20_000_000},
    )
    assert changed.status_code == 200, changed.text
    both_off = await client.patch(
        f"/tenants/{tenant.id}", json={"delivery_enabled": False, "pickup_enabled": False}
    )
    assert both_off.json()["detail"]["code"] == "fulfilment_required"

    public = (await client.get("/storefront/varaq")).json()
    assert (public["pickup_enabled"], public["delivery_enabled"], public["delivery_fee"]) == (
        True,
        True,
        1_500_000,
    )
    assert public["free_delivery_from"] == 20_000_000
    assert "order_seq" not in public
