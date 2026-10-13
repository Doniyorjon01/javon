"""The store's shelf through the API: who may do what, stock rules, isolation."""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_inventory
from models import MemberRole, Plan, Tenant, User
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


async def store(db: AsyncSession, slug: str = "varaq") -> tuple[Tenant, User, User]:
    owner = await make_user(db, "Owner")
    staff = await make_user(db, "Staff")
    tenant = await make_tenant(db, slug, owner)
    await add_member(db, tenant, staff, MemberRole.STAFF)
    return tenant, owner, staff


async def test_owner_puts_a_book_on_sale(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, staff = await store(db)
    book = await make_book(db, "O'tkan kunlar", isbn="9780306406157")
    url = f"/tenants/{tenant.id}/inventory"

    await sign_in(client, staff)
    assert (await client.post(url, json={"book_id": book.id, "price": 4_500_000})).status_code == 403

    await sign_in(client, owner)
    created = await client.post(url, json={"book_id": book.id, "price": 4_500_000, "quantity": 3})
    assert created.status_code == 201, created.text
    item = created.json()
    assert (item["price"], item["quantity"], item["is_visible"]) == (4_500_000, 3, True)
    assert item["book"]["title"] == "O'tkan kunlar"

    again = await client.post(url, json={"book_id": book.id, "price": 1})
    assert again.status_code == 409
    assert again.json()["detail"] == again.json()["detail"] | {
        "code": "inventory_item_exists",
        "item_id": item["id"],
    }

    by_isbn = await client.get(f"{url}/isbn/978-0-306-40615-7")
    assert by_isbn.json()["id"] == item["id"]


async def test_only_books_the_store_may_see_can_be_added(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, _ = await store(db)
    other, other_owner, _ = await store(db, "boshqa")
    await sign_in(client, other_owner)
    foreign_pending = (
        await client.post(
            f"/tenants/{other.id}/catalog/books", json={"title": "Begona", "authors": ["Kimdir"]}
        )
    ).json()

    await sign_in(client, owner)
    own_pending = (
        await client.post(
            f"/tenants/{tenant.id}/catalog/books", json={"title": "Oʻzimniki", "authors": ["Men"]}
        )
    ).json()
    url = f"/tenants/{tenant.id}/inventory"
    assert (await client.post(url, json={"book_id": foreign_pending["id"], "price": 100})).status_code == 404
    assert (await client.post(url, json={"book_id": own_pending["id"], "price": 100})).status_code == 201


async def test_staff_counts_stock_but_does_not_set_prices(client: AsyncClient, db: AsyncSession) -> None:
    tenant, _, staff = await store(db)
    item = await make_item(tenant, await make_book(db), price=1000, quantity=2)
    url = f"/tenants/{tenant.id}/inventory/{item.id}"

    await sign_in(client, staff)
    counted = await client.patch(url, json={"quantity": 7})
    assert counted.json()["quantity"] == 7
    assert (await client.patch(url, json={"price": 1})).status_code == 403
    assert (await client.patch(url, json={"is_visible": False})).status_code == 403
    assert (await client.patch(url, json={"quantity": None})).status_code == 422
    assert (await client.delete(url)).status_code == 403


async def test_adjust_never_goes_below_zero(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, _ = await store(db)
    item = await make_item(tenant, await make_book(db), quantity=2)
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/inventory/{item.id}/adjust"

    assert (await client.post(url, json={"delta": 5})).json()["quantity"] == 7
    refused = await client.post(url, json={"delta": -8})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "stock_out_of_range"
    assert refused.json()["detail"]["quantity"] == 7
    assert (await client.post(url, json={"delta": -7})).json()["quantity"] == 0


async def test_parallel_adjustments_are_not_lost(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, _ = await store(db)
    item = await make_item(tenant, await make_book(db), quantity=0)
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/inventory/{item.id}/adjust"
    await asyncio.gather(*(client.post(url, json={"delta": 1}) for _ in range(20)))
    assert (await client.get(f"/tenants/{tenant.id}/inventory/{item.id}")).json()["quantity"] == 20


async def test_list_search_filters_and_removal(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, _ = await store(db)
    a = await make_item(tenant, await make_book(db, "Alpomish", ["Xalq"]), quantity=0)
    b = await make_item(tenant, await make_book(db, "Boburnoma", ["Zahiriddin Bobur"]), quantity=4)
    await make_item(
        tenant, await make_book(db, "Chol va dengiz", ["Ernest Xeminguey"]), quantity=1, is_visible=False
    )
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/inventory"

    async def titles(**params: object) -> list[str]:
        resp = await client.get(url, params=params)
        assert resp.status_code == 200, resp.text
        return [row["book"]["title"] for row in resp.json()["items"]]

    assert await titles(sort="title") == ["Alpomish", "Boburnoma", "Chol va dengiz"]
    assert await titles(q="Бобур") == ["Boburnoma"]  # Cyrillic query, Latin book
    assert await titles(in_stock=False) == ["Alpomish"]
    assert await titles(visible=False) == ["Chol va dengiz"]
    assert (await titles(sort="quantity"))[0] == "Alpomish"

    assert (await client.delete(f"{url}/{a.id}")).status_code == 204
    assert (await client.get(f"{url}/{a.id}")).status_code == 404
    assert "Alpomish" not in await titles()
    # Removed books can be put on sale again.
    assert (await client.post(url, json={"book_id": a.book_id, "price": 10})).status_code == 201
    assert b.id  # untouched


async def test_another_store_cannot_touch_my_shelf(client: AsyncClient, db: AsyncSession) -> None:
    tenant, _, _ = await store(db)
    other, other_owner, _ = await store(db, "boshqa")
    item = await make_item(tenant, await make_book(db))
    await sign_in(client, other_owner)
    url = f"/tenants/{other.id}/inventory/{item.id}"
    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"quantity": 0})).status_code == 404
    assert (await client.post(f"{url}/adjust", json={"delta": -1})).status_code == 404
    assert (await client.get(f"/tenants/{other.id}/inventory")).json()["items"] == []


async def test_plan_limits_the_number_of_books(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(db_inventory.PLAN_ITEM_LIMITS, Plan.STANDARD, 2)
    tenant, owner, _ = await store(db)
    books = [await make_book(db, f"Kitob {i}") for i in range(3)]
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/inventory"
    codes = [(await client.post(url, json={"book_id": b.id, "price": 100})).status_code for b in books]
    assert codes == [201, 201, 403]


async def test_parallel_adds_of_one_book_make_one_row(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner, _ = await store(db)
    book = await make_book(db)
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/inventory"
    responses = await asyncio.gather(
        *(client.post(url, json={"book_id": book.id, "price": 100}) for _ in range(8))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 1 and set(codes) == {201, 409}
