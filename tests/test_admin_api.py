"""Platform admin: stores, suspension, metrics across stores, background jobs."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Job, JobStatus, Tenant
from tests.factories import make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def clean_rate_limits() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


async def place_order(client: AsyncClient, slug: str, book_id: int) -> None:
    resp = await client.post(
        f"/storefront/{slug}/orders",
        json={
            "idempotency_key": str(uuid.uuid4()),
            "customer_name": "Aziz",
            "phone": "+998901234567",
            "delivery_type": "pickup",
            "items": [{"book_id": book_id, "quantity": 1}],
        },
    )
    assert resp.status_code == 201, resp.text


async def test_only_the_platform_admin(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    for path in ("/system/metrics", "/system/tenants", f"/system/tenants/{tenant.id}", "/system/jobs"):
        assert (await client.get(path)).status_code == 403
    resp = await client.post(f"/system/tenants/{tenant.id}/suspend", json={"reason": "spam"})
    assert resp.status_code == 403


async def test_stores_list_detail_and_metrics(client: AsyncClient, db: AsyncSession) -> None:
    admin = await make_user(db, is_platform_admin=True)
    owner = await make_user(db, "Doniyor")
    varaq = await make_tenant(db, "varaq", owner, name="Varaq kitoblari")
    kitobxon = await make_tenant(db, "kitobxon", name="Kitobxon")
    await make_tenant(db, "yopiq", name="Yopiq do'kon")
    await db.execute(
        update(Tenant)
        .where(Tenant.slug == "yopiq")
        .values(trial_ends_at=datetime.now(UTC) - timedelta(days=9))
    )
    await db.commit()
    book = await make_book(db)
    await make_item(varaq, book, quantity=9)
    await make_item(kitobxon, book, quantity=9)
    for _ in range(3):
        await place_order(client, "varaq", book.id)
    await place_order(client, "kitobxon", book.id)

    await sign_in(client, admin)
    page = (await client.get("/system/tenants")).json()
    assert page["total"] == 3
    by_slug = {store["slug"]: store for store in page["items"]}
    # Order numbers cross RLS through the aggregate function, store by store.
    assert by_slug["varaq"]["orders_30d"] == 3
    assert by_slug["varaq"]["sales_30d"] == 3 * 4_500_000
    assert by_slug["kitobxon"]["orders_30d"] == 1
    assert by_slug["yopiq"]["orders_30d"] == 0 and by_slug["yopiq"]["access"] == "expired"
    assert by_slug["varaq"]["owner"]["first_name"] == "Doniyor"

    assert [
        s["slug"] for s in (await client.get("/system/tenants", params={"q": "VARAQ"})).json()["items"]
    ] == ["varaq"]
    assert [
        s["slug"] for s in (await client.get("/system/tenants", params={"closed": True})).json()["items"]
    ] == ["yopiq"]
    assert (await client.get("/system/tenants", params={"closed": False})).json()["total"] == 2

    detail = (await client.get(f"/system/tenants/{varaq.id}")).json()
    assert detail["items"] == 1 and detail["staff"] == 0
    assert detail["bot_username"] is None and detail["payments"] == []
    assert (await client.get("/system/tenants/999999")).status_code == 404

    metrics = (await client.get("/system/metrics")).json()
    assert metrics["stores"] == 3
    assert metrics["by_access"]["trial"] == 2 and metrics["by_access"]["expired"] == 1
    assert metrics["orders_7d"] == 4 and metrics["orders_30d"] == 4
    assert metrics["active_stores_7d"] == 2
    assert metrics["sales_30d"] == 4 * 4_500_000
    assert metrics["jobs_queued"] >= 4  # the new-order notifications


async def test_suspend_and_activate(client: AsyncClient, db: AsyncSession) -> None:
    admin, owner = await make_user(db, is_platform_admin=True), await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, admin)
    assert (await client.post(f"/system/tenants/{tenant.id}/suspend", json={"reason": ""})).status_code == 422
    resp = await client.post(f"/system/tenants/{tenant.id}/suspend", json={"reason": "Qalbaki kitoblar"})
    assert resp.status_code == 200
    assert resp.json()["access"] == "suspended" and resp.json()["suspended_reason"] == "Qalbaki kitoblar"
    notice = await db.scalar(
        select(Job.payload).where(Job.tenant_id == tenant.id, Job.kind == "owner_notice")
    )
    assert notice == {"notice": "suspended"}
    assert (await client.get("/storefront/varaq")).status_code == 404

    await sign_in(client, owner)
    blocked = await client.patch(f"/tenants/{tenant.id}", json={"name": "X"})
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "store_suspended"
    sub = (await client.get(f"/tenants/{tenant.id}/subscription")).json()
    assert sub["state"] == "suspended" and sub["suspended_reason"] == "Qalbaki kitoblar"

    await sign_in(client, admin)
    resp = await client.post(f"/system/tenants/{tenant.id}/activate")
    assert resp.json()["status"] == "trial" and resp.json()["suspended_reason"] is None
    assert (await client.get("/storefront/varaq")).status_code == 200


async def test_failed_jobs_can_be_retried(client: AsyncClient, db: AsyncSession) -> None:
    admin = await make_user(db, is_platform_admin=True)
    failed = Job(kind="order_created", payload={"order_id": 1}, status=JobStatus.FAILED, attempts=5)
    done = Job(kind="order_created", payload={"order_id": 2}, status=JobStatus.DONE)
    db.add_all([failed, done])
    await db.commit()
    await sign_in(client, admin)

    listed = (await client.get("/system/jobs", params={"status": "failed"})).json()
    assert [job["id"] for job in listed["items"]] == [failed.id]
    retried = await client.post(f"/system/jobs/{failed.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued" and retried.json()["attempts"] == 0
    again = await client.post(f"/system/jobs/{done.id}/retry")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "job_not_retryable"
    assert (await client.get("/system/jobs", params={"kind": "nope"})).status_code == 422
