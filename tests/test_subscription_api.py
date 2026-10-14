"""Plans, the subscription clock in the API, and payments recorded by the platform admin."""

import asyncio
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_subscription
from database.config import SessionLocal
from models import Job, MemberRole, Tenant
from schemas.subscription import SubscriptionPaymentIn
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
async def clean_rate_limits() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


async def set_dates(db: AsyncSession, tenant: Tenant, **values: object) -> None:
    await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(**values))
    await db.commit()


async def notices(db: AsyncSession, tenant_id: int) -> list[str]:
    rows = await db.scalars(
        select(Job.payload).where(Job.tenant_id == tenant_id, Job.kind == "owner_notice").order_by(Job.id)
    )
    return [row["notice"] for row in rows]


async def test_plans_are_public(client: AsyncClient) -> None:
    resp = await client.get("/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trial_days"] == settings.TRIAL_DAYS
    standard = next(p for p in body["plans"] if p["plan"] == "standard")
    assert standard == {
        "plan": "standard",
        "monthly_price": 39_000_000,
        "yearly_price": 390_000_000,
        "item_limit": 3000,
        "staff_limit": 5,
        "excel_import": True,
    }


async def test_owner_sees_the_trial_and_how_to_pay(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await make_item(tenant, await make_book(db))
    await sign_in(client, owner)
    resp = await client.get(f"/tenants/{tenant.id}/subscription")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "trial"
    assert body["plan"] == "standard"
    assert body["items_used"] == 1 and body["item_limit"] == 3000
    assert body["staff_used"] == 0 and body["staff_limit"] == 5
    assert body["pay_to"] == {
        "card_number": "8600123412341234",
        "card_holder": "Javon MChJ",
        "support_telegram": "javon_support",
    }
    closes = datetime.fromisoformat(body["closes_at"])
    assert closes - datetime.fromisoformat(body["access_until"]) == timedelta(days=3)

    me = (await client.get("/auth/me")).json()
    assert me["stores"][0]["access"] == "trial"


async def test_staff_cannot_see_the_subscription(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    staff = await make_user(db)
    await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    assert (await client.get(f"/tenants/{tenant.id}/subscription")).status_code == 403


async def test_unpaid_store_closes_after_the_grace_days_and_reopens_on_payment(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await make_user(db)
    admin = await make_user(db, is_platform_admin=True)
    tenant = await make_tenant(db, "varaq", owner)
    await make_item(tenant, await make_book(db))
    now = datetime.now(UTC)

    # Trial ended yesterday: grace days, everything still works.
    await set_dates(db, tenant, trial_ends_at=now - DAY)
    assert (await client.get("/storefront/varaq")).status_code == 200
    await sign_in(client, owner)
    assert (await client.patch(f"/tenants/{tenant.id}", json={"name": "Varaq 2"})).status_code == 200
    assert (await client.get(f"/tenants/{tenant.id}/subscription")).json()["state"] == "grace"

    # Four days ago: closed. The storefront is gone, the panel is read-only.
    await set_dates(db, tenant, trial_ends_at=now - 4 * DAY)
    assert (await client.get("/storefront/varaq")).status_code == 404
    resp = await client.patch(f"/tenants/{tenant.id}", json={"name": "Varaq 3"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "subscription_expired"
    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 200
    assert (await client.get(f"/tenants/{tenant.id}/subscription")).json()["state"] == "expired"
    assert (await client.get("/auth/me")).json()["stores"][0]["access"] == "expired"

    # Only the platform admin records payments.
    pay = {"plan": "start", "months": 1, "note": "karta, chek #4411"}
    assert (
        await client.post(f"/system/tenants/{tenant.id}/subscription/payments", json=pay)
    ).status_code == 403
    await sign_in(client, admin)
    resp = await client.post(f"/system/tenants/{tenant.id}/subscription/payments", json=pay)
    assert resp.status_code == 201, resp.text
    payment = resp.json()
    assert payment["amount"] == 19_000_000  # the list price when no amount is given
    start = datetime.fromisoformat(payment["period_start"])
    assert abs((start - datetime.now(UTC)).total_seconds()) < 60  # closed store: starts today
    assert await notices(db, tenant.id) == ["paid"]

    # Open again, on the new plan.
    assert (await client.get("/storefront/varaq")).status_code == 200
    await sign_in(client, owner)
    body = (await client.get(f"/tenants/{tenant.id}/subscription")).json()
    assert body["state"] == "active" and body["status"] == "active" and body["plan"] == "start"
    assert body["payments"][0]["note"] == "karta, chek #4411"
    assert (await client.patch(f"/tenants/{tenant.id}", json={"name": "Varaq 3"})).status_code == 200


async def test_early_payment_extends_the_trial_and_void_takes_it_back(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant = await make_tenant(db, "varaq")
    admin = await make_user(db, is_platform_admin=True)
    trial_end = datetime.now(UTC) + 5 * DAY
    await set_dates(db, tenant, trial_ends_at=trial_end)
    await sign_in(client, admin)

    first = (
        await client.post(
            f"/system/tenants/{tenant.id}/subscription/payments",
            json={"plan": "standard", "months": 12, "amount": 350_000_000},
        )
    ).json()
    assert datetime.fromisoformat(first["period_start"]) == trial_end
    assert first["amount"] == 350_000_000
    second = (
        await client.post(
            f"/system/tenants/{tenant.id}/subscription/payments", json={"plan": "pro", "months": 1}
        )
    ).json()
    assert second["period_start"] == first["period_end"]

    detail = (await client.get(f"/system/tenants/{tenant.id}")).json()
    assert detail["paid_until"] == second["period_end"]
    assert detail["plan"] == "pro"

    voided = await client.post(f"/system/subscription-payments/{second['id']}/void")
    assert voided.status_code == 200 and voided.json()["is_active"] is False
    detail = (await client.get(f"/system/tenants/{tenant.id}")).json()
    assert detail["paid_until"] == first["period_end"]
    assert (await client.post(f"/system/subscription-payments/{second['id']}/void")).status_code == 404

    await client.post(f"/system/subscription-payments/{first['id']}/void")
    detail = (await client.get(f"/system/tenants/{tenant.id}")).json()
    assert detail["paid_until"] is None
    assert detail["status"] == "trial"
    history = (await client.get(f"/system/tenants/{tenant.id}/subscription/payments")).json()
    assert history["total"] == 2


async def test_manual_correction_and_validation(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    admin = await make_user(db, is_platform_admin=True)
    await sign_in(client, admin)
    url = f"/system/tenants/{tenant.id}"
    bad = await client.post(f"{url}/subscription/payments", json={"plan": "gold", "months": 1})
    assert bad.status_code == 422
    bad = await client.post(f"{url}/subscription/payments", json={"plan": "start", "months": 0})
    assert bad.status_code == 422
    later = (datetime.now(UTC) + 30 * DAY).isoformat()
    resp = await client.patch(f"{url}/subscription", json={"trial_ends_at": later, "plan": "pro"})
    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro" and resp.json()["access"] == "trial"
    assert (
        await client.post("/system/tenants/999999/subscription/payments", json={"plan": "start", "months": 1})
    ).status_code == 404


def xlsx() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(["ISBN", "Nomi", "Muallif", "Narx", "Soni"])
    sheet.append(["9789943000000", "Kitob", "Muallif", "45000", "2"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


async def test_excel_import_needs_the_standard_plan(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await set_dates(db, tenant, plan="start")
    await sign_in(client, owner)
    resp = await client.post(
        f"/tenants/{tenant.id}/inventory/imports",
        files={"file": ("kitoblar.xlsx", xlsx(), "application/octet-stream")},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "plan_feature_unavailable"
    await set_dates(db, tenant, plan="standard")
    resp = await client.post(
        f"/tenants/{tenant.id}/inventory/imports",
        files={"file": ("kitoblar.xlsx", xlsx(), "application/octet-stream")},
    )
    assert resp.status_code in (202, 422), resp.text  # past the plan check
    assert resp.json().get("detail", {}).get("code") != "plan_feature_unavailable"


async def test_two_payments_at_once_both_count(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    admin = await make_user(db, is_platform_admin=True)
    await set_dates(db, tenant, trial_ends_at=datetime.now(UTC) - 30 * DAY)

    async def pay() -> None:
        async with SessionLocal() as session:
            await db_subscription.record_payment(
                session, tenant.id, SubscriptionPaymentIn(plan="start", months=1), admin.id
            )

    await asyncio.gather(pay(), pay())
    paid_until = await db.scalar(
        select(Tenant.paid_until).where(Tenant.id == tenant.id), execution_options={"populate_existing": True}
    )
    # Two months from (about) today, not one month twice over the same days.
    assert paid_until - datetime.now(UTC) > 55 * DAY
