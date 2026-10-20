"""Checkout, stock safety, idempotency, tracking and the store's order handling."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.config import SessionLocal, bind_tenant
from models import Customer, InventoryItem, Job, MemberRole, Order, Tenant, User
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in
from workers import main as worker

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def clean_rate_limits() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


@pytest.fixture
async def shop(db: AsyncSession) -> tuple[Tenant, User, dict[str, InventoryItem]]:
    owner = await make_user(db, "Owner")
    tenant = await make_tenant(db, "varaq", owner)
    items = {
        "kunlar": await make_item(tenant, await make_book(db, "O'tkan kunlar"), price=4_500_000, quantity=3),
        "chayon": await make_item(
            tenant, await make_book(db, "Mehrobdan chayon"), price=3_000_000, quantity=1
        ),
    }
    return tenant, owner, items


def checkout(*lines: tuple[InventoryItem, int], **fields: object) -> dict:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "customer_name": "Aziz",
        "phone": "90 123 45 67",
        "delivery_type": "pickup",
        "items": [{"book_id": item.book_id, "quantity": quantity} for item, quantity in lines],
        **fields,
    }


async def stock(tenant: Tenant, item: InventoryItem) -> int:
    async with SessionLocal() as session:
        await bind_tenant(session, tenant.id)
        return await session.scalar(select(InventoryItem.quantity).where(InventoryItem.id == item.id))


async def test_pickup_order_end_to_end(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, owner, items = shop
    resp = await client.post(
        "/storefront/varaq/orders", json=checkout((items["kunlar"], 2), (items["chayon"], 1))
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["number"] == 1
    assert (order["subtotal"], order["delivery_fee"], order["total"]) == (12_000_000, 0, 12_000_000)
    assert order["phone_masked"] == "+998 ** *** 45 67"
    assert "customer_phone" not in order
    assert [(i["title"], i["quantity"], i["line_total"]) for i in order["items"]] == [
        ("O'tkan kunlar", 2, 9_000_000),
        ("Mehrobdan chayon", 1, 3_000_000),
    ]
    assert await stock(tenant, items["kunlar"]) == 1
    assert await stock(tenant, items["chayon"]) == 0

    # Tracking link works only with the right token.
    track = f"/storefront/varaq/orders/{order['id']}"
    assert (await client.get(track, params={"token": order["tracking_token"]})).json()["status"] == "new"
    assert (await client.get(track, params={"token": "x" * 22})).status_code == 404

    # The outbox job was written with the order, and the worker runs it.
    job = await db.scalar(select(Job))
    assert (job.kind, job.tenant_id, job.payload) == ("order_created", tenant.id, {"order_id": order["id"]})
    assert await worker.process_one() is True

    # The store sees the full phone number.
    await sign_in(client, owner)
    full = (await client.get(f"/tenants/{tenant.id}/orders/{order['id']}")).json()
    assert full["customer_phone"] == "+998901234567"


async def test_my_orders_statuses(client: AsyncClient, shop: tuple) -> None:
    tenant, owner, items = shop
    first = (await client.post("/storefront/varaq/orders", json=checkout((items["kunlar"], 1)))).json()
    second = (await client.post("/storefront/varaq/orders", json=checkout((items["chayon"], 1)))).json()
    await sign_in(client, owner)
    await client.post(f"/tenants/{tenant.id}/orders/{first['id']}/status", json={"status": "accepted"})
    client.cookies.clear()

    refs = [
        {"id": first["id"], "token": first["tracking_token"]},
        {"id": second["id"], "token": "x" * 22},  # wrong token: left out, like a missing order
        {"id": 999_999, "token": first["tracking_token"]},
    ]
    resp = await client.post("/storefront/varaq/orders/statuses", json={"orders": refs})
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"id": first["id"], "number": 1, "status": "accepted", "payment_status": "unpaid"}]

    too_many = [{"id": i, "token": "x" * 22} for i in range(1, 52)]
    resp = await client.post("/storefront/varaq/orders/statuses", json={"orders": too_many})
    assert resp.status_code == 422


async def test_delivery_fee_and_free_delivery(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, _, items = shop
    body = checkout((items["kunlar"], 1), delivery_type="delivery", address="Chilonzor 9, 12-uy")
    refused = await client.post("/storefront/varaq/orders", json=body)
    assert refused.json()["detail"]["code"] == "delivery_unavailable"

    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant.id)
        .values(delivery_enabled=True, delivery_fee=1_500_000, free_delivery_from=9_000_000)
    )
    await db.commit()
    paid = (
        await client.post("/storefront/varaq/orders", json={**body, "idempotency_key": str(uuid.uuid4())})
    ).json()
    assert (paid["delivery_fee"], paid["total"]) == (1_500_000, 6_000_000)
    free = (
        await client.post(
            "/storefront/varaq/orders",
            json=checkout((items["kunlar"], 2), delivery_type="delivery", address="Yunusobod 4"),
        )
    ).json()
    assert (free["delivery_fee"], free["total"]) == (0, 9_000_000)

    no_address = await client.post(
        "/storefront/varaq/orders", json=checkout((items["kunlar"], 1), delivery_type="delivery")
    )
    assert no_address.status_code == 422


async def test_retry_with_the_same_key_returns_the_same_order(
    client: AsyncClient, db: AsyncSession, shop: tuple
) -> None:
    tenant, _, items = shop
    body = checkout((items["kunlar"], 1))
    first = await client.post("/storefront/varaq/orders", json=body)
    retry = await client.post("/storefront/varaq/orders", json=body)
    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json()["id"] == first.json()["id"]
    assert retry.json()["tracking_token"] == first.json()["tracking_token"]
    assert await stock(tenant, items["kunlar"]) == 2  # taken once

    changed = await client.post("/storefront/varaq/orders", json={**body, "customer_name": "Boshqa"})
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "idempotency_conflict"


async def test_same_key_in_parallel_makes_one_order(
    client: AsyncClient, db: AsyncSession, shop: tuple
) -> None:
    tenant, _, items = shop
    body = checkout((items["kunlar"], 1))
    responses = await asyncio.gather(*(client.post("/storefront/varaq/orders", json=body) for _ in range(6)))
    assert sorted(r.status_code for r in responses).count(201) == 1
    assert {r.json()["id"] for r in responses} == {responses[0].json()["id"]}
    assert await stock(tenant, items["kunlar"]) == 2


async def test_last_copies_cannot_be_sold_twice(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    """Ten buyers race for three copies: exactly three orders, never negative stock."""
    tenant, _, items = shop
    responses = await asyncio.gather(
        *(client.post("/storefront/varaq/orders", json=checkout((items["kunlar"], 1))) for _ in range(10))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 3 + [409] * 7, codes
    assert sorted(r.json()["number"] for r in responses if r.status_code == 201) == [1, 2, 3]
    assert await stock(tenant, items["kunlar"]) == 0
    lost = next(r for r in responses if r.status_code == 409).json()["detail"]
    assert lost["code"] == "out_of_stock"
    assert lost["items"] == [{"book_id": items["kunlar"].book_id, "available": 0}]


async def test_unavailable_books_are_named(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, _, items = shop
    hidden = await make_item(tenant, await make_book(db, "Yashirin"), is_visible=False)
    elsewhere = await make_book(db, "Bu doʻkonda yoʻq")
    body = checkout((items["kunlar"], 1), (hidden, 1))
    body["items"].append({"book_id": elsewhere.id, "quantity": 1})
    resp = await client.post("/storefront/varaq/orders", json=body)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "order_items_unavailable"
    assert resp.json()["detail"]["book_ids"] == sorted([hidden.book_id, elsewhere.id])
    assert await stock(tenant, items["kunlar"]) == 3  # nothing taken


@pytest.mark.parametrize(
    "change",
    [
        {"phone": "12"},
        {"customer_name": "A"},
        {"items": []},
        {"payment_method": "card"},
        {"tenant_id": 1},  # mass assignment
        {"price": 1},
    ],
)
async def test_checkout_validation(client: AsyncClient, shop: tuple, change: dict) -> None:
    _, _, items = shop
    resp = await client.post("/storefront/varaq/orders", json={**checkout((items["kunlar"], 1)), **change})
    assert resp.status_code == 422


async def test_duplicate_lines_are_refused(client: AsyncClient, shop: tuple) -> None:
    _, _, items = shop
    body = checkout((items["kunlar"], 1), (items["kunlar"], 1))
    assert (await client.post("/storefront/varaq/orders", json=body)).status_code == 422


async def test_rate_limit_per_ip(client: AsyncClient, shop: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, items = shop
    monkeypatch.setattr(settings, "ORDER_RATE_LIMIT", 2)
    codes = [
        (await client.post("/storefront/varaq/orders", json=checkout((items["chayon"], 1)))).status_code
        for _ in range(3)
    ]
    assert codes[2] == 429
    last = await client.post("/storefront/varaq/orders", json=checkout((items["chayon"], 1)))
    assert last.json()["detail"]["code"] == "too_many_requests"
    assert last.headers["retry-after"] == str(settings.ORDER_RATE_WINDOW_S)


async def test_one_customer_per_phone(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, _, items = shop
    await client.post(
        "/storefront/varaq/orders", json=checkout((items["kunlar"], 1), phone="+998 90 123-45-67")
    )
    await client.post(
        "/storefront/varaq/orders",
        json=checkout((items["kunlar"], 1), phone="998901234567", customer_name="Aziz aka"),
    )
    async with SessionLocal() as session:
        await bind_tenant(session, tenant.id)
        customers = list(await session.scalars(select(Customer)))
    assert [(c.phone, c.name) for c in customers] == [("+998901234567", "Aziz aka")]


# --------------------------------------------------------------------------- #
# The store's side
# --------------------------------------------------------------------------- #
async def test_status_flow_and_cancellation(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, _, items = shop
    staff = await make_user(db, "Staff")
    await add_member(db, tenant, staff, MemberRole.STAFF)
    pickup = (await client.post("/storefront/varaq/orders", json=checkout((items["kunlar"], 2)))).json()
    other = (await client.post("/storefront/varaq/orders", json=checkout((items["chayon"], 1)))).json()

    await sign_in(client, staff)  # staff handles orders
    url = f"/tenants/{tenant.id}/orders"

    async def move(order_id: int, new_status: str, **extra: object):
        return await client.post(f"{url}/{order_id}/status", json={"status": new_status, **extra})

    assert (await move(pickup["id"], "completed")).json()["detail"]["code"] == "order_status_invalid"
    assert (await move(pickup["id"], "accepted")).json()["accepted_at"] is not None
    assert (await move(pickup["id"], "shipping")).status_code == 409  # pickup is never shipped
    done = (await move(pickup["id"], "completed")).json()
    assert (done["status"], done["payment_status"]) == ("completed", "paid")
    assert (await move(pickup["id"], "cancelled")).status_code == 409  # final

    cancelled = (await move(other["id"], "cancelled", reason="Mijoz bekor qildi")).json()
    assert (cancelled["status"], cancelled["cancel_reason"]) == ("cancelled", "Mijoz bekor qildi")
    assert await stock(tenant, items["chayon"]) == 1  # back on the shelf
    buyer_view = await client.get(
        f"/storefront/varaq/orders/{other['id']}", params={"token": other["tracking_token"]}
    )
    assert buyer_view.json()["cancel_reason"] == "Mijoz bekor qildi"

    stats = (await client.get(f"{url}/stats")).json()["by_status"]
    assert stats == {"new": 0, "accepted": 0, "shipping": 0, "completed": 1, "cancelled": 1}
    kinds = list(await db.scalars(select(Job.kind).order_by(Job.id)))
    assert kinds.count("order_status_changed") == 3


async def test_list_search_and_isolation(client: AsyncClient, db: AsyncSession, shop: tuple) -> None:
    tenant, owner, items = shop
    await client.post("/storefront/varaq/orders", json=checkout((items["kunlar"], 1), customer_name="Laylo"))
    second = (
        await client.post(
            "/storefront/varaq/orders", json=checkout((items["kunlar"], 1), phone="+998 93 777 00 11")
        )
    ).json()

    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/orders"

    async def numbers(**params: object) -> list[int]:
        return [o["number"] for o in (await client.get(url, params=params)).json()["items"]]

    assert await numbers() == [2, 1]  # newest first
    assert await numbers(q="laylo") == [1]
    assert await numbers(q="777 00") == [2]
    assert await numbers(q="2") == [2]
    assert await numbers(status="cancelled") == []

    other_owner = await make_user(db, "Other")
    other = await make_tenant(db, "boshqa", other_owner)
    await sign_in(client, other_owner)
    assert (await client.get(f"/tenants/{other.id}/orders/{second['id']}")).status_code == 404
    assert (await client.get(f"/tenants/{other.id}/orders")).json()["items"] == []
    move = await client.post(f"/tenants/{other.id}/orders/{second['id']}/status", json={"status": "accepted"})
    assert move.status_code == 404
    assert await db.scalar(select(func.count()).select_from(Order).where(Order.status == "accepted")) == 0
