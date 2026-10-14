"""The owner's statistics: totals, days, best sellers, isolation."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import InventoryItem, MemberRole
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def clean_rate_limits() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


async def order(client: AsyncClient, slug: str, item: InventoryItem, quantity: int, phone: str) -> int:
    resp = await client.post(
        f"/storefront/{slug}/orders",
        json={
            "idempotency_key": str(uuid.uuid4()),
            "customer_name": "Aziz",
            "phone": phone,
            "delivery_type": "pickup",
            "items": [{"book_id": item.book_id, "quantity": quantity}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_store_stats(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    kunlar = await make_item(tenant, await make_book(db, "O'tkan kunlar"), price=4_500_000, quantity=10)
    chayon = await make_item(tenant, await make_book(db, "Mehrobdan chayon"), price=3_000_000, quantity=10)
    await make_item(tenant, await make_book(db, "Tugagan"), quantity=0)
    other = await make_tenant(db, "kitobxon")
    foreign = await make_item(other, await make_book(db, "Boshqa"), price=1_000_000)

    first = await order(client, "varaq", kunlar, 2, "+998901111111")
    await order(client, "varaq", chayon, 1, "+998901111111")
    cancelled = await order(client, "varaq", chayon, 3, "+998902222222")
    await order(client, "kitobxon", foreign, 1, "+998903333333")

    await sign_in(client, owner)
    for status_name in ("accepted", "completed"):
        resp = await client.post(f"/tenants/{tenant.id}/orders/{first}/status", json={"status": status_name})
        assert resp.status_code == 200, resp.text
    await client.post(f"/tenants/{tenant.id}/orders/{cancelled}/status", json={"status": "cancelled"})

    resp = await client.get(f"/tenants/{tenant.id}/stats", params={"days": 7})
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["orders"] == 3
    assert stats["by_status"]["cancelled"] == 1 and stats["by_status"]["completed"] == 1
    assert stats["by_channel"] == {"web": 3, "telegram": 0}
    assert stats["sales"] == 2 * 4_500_000 + 3_000_000
    assert stats["completed_sales"] == 2 * 4_500_000
    assert stats["average_order"] == (2 * 4_500_000 + 3_000_000) // 2
    assert stats["customers"] == 1 and stats["returning_customers"] == 1
    assert len(stats["by_day"]) == 7
    assert stats["by_day"][-1]["orders"] == 2
    assert sum(day["orders"] for day in stats["by_day"]) == 2
    assert [book["title"] for book in stats["top_books"]] == ["O'tkan kunlar", "Mehrobdan chayon"]
    assert stats["inventory"] == {"items": 3, "visible": 3, "out_of_stock": 1}

    assert (await client.get(f"/tenants/{tenant.id}/stats", params={"days": 0})).status_code == 422


async def test_staff_do_not_see_sales(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    staff = await make_user(db)
    await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    assert (await client.get(f"/tenants/{tenant.id}/stats")).status_code == 403
