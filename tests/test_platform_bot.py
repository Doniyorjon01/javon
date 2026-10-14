"""The platform bot (owners' phones), owner notices, reminders and clean-up."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.config import SessionLocal, bind_tenant
from models import InventoryImport, Job, StaffInvite, Tenant, User, UserSession
from services.platform_bot import webhook_secret
from tests.conftest import TEST_BOT_TOKEN
from tests.factories import make_tenant, make_user, sign_in
from tests.fake_telegram import FakeTelegram
from workers import main as worker
from workers import subscriptions

pytestmark = pytest.mark.db

OWNER_TG = 4_400_100


@pytest.fixture(autouse=True)
async def clean_redis() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


async def run_jobs() -> None:
    while await worker.process_one():
        pass


_update_ids = iter(range(10_000, 99_999))


async def send(client: AsyncClient, message: dict[str, Any], secret: str | None = None) -> int:
    body = {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 1,
            "chat": {"id": OWNER_TG, "type": "private"},
            "from": {"id": OWNER_TG, "first_name": "Doniyor", "language_code": "uz"},
            **message,
        },
    }
    resp = await client.post(
        "/telegram/platform",
        json=body,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret or webhook_secret()},
    )
    return resp.status_code


async def test_owner_shares_their_phone(
    client: AsyncClient, db: AsyncSession, telegram: FakeTelegram
) -> None:
    db.add(User(telegram_id=OWNER_TG, first_name="Doniyor", language="ru"))
    await db.commit()

    assert await send(client, {"text": "/start"}, secret="wrong") == 401
    assert await send(client, {"text": "/start"}) == 200
    start = telegram.sent(OWNER_TG)[-1]
    assert start.token == TEST_BOT_TOKEN
    assert "Здравствуйте" in start.params["text"]  # the owner's language
    assert start.params["reply_markup"]["keyboard"][0][0]["request_contact"] is True

    # Someone else's contact is refused.
    assert await send(client, {"contact": {"phone_number": "+998901112233", "user_id": 999}}) == 200
    phone = await db.scalar(select(User.phone).where(User.telegram_id == OWNER_TG))
    assert phone is None

    assert await send(client, {"contact": {"phone_number": "998 90 765 43 21", "user_id": OWNER_TG}}) == 200
    db.expire_all()
    assert await db.scalar(select(User.phone).where(User.telegram_id == OWNER_TG)) == "+998907654321"
    assert telegram.sent(OWNER_TG)[-1].params["reply_markup"] == {"remove_keyboard": True}

    me = await make_user(db)
    await sign_in(client, me)
    assert (await client.get("/auth/me")).json()["user"]["phone"] is None


async def test_contact_from_a_stranger(client: AsyncClient, db: AsyncSession, telegram: FakeTelegram) -> None:
    assert await send(client, {"contact": {"phone_number": "+998901112233", "user_id": OWNER_TG}}) == 200
    assert "javon.uz" in telegram.sent_texts(OWNER_TG)[-1]
    assert await send(client, {"text": "salom"}) == 200
    assert "https://javon.uz" in telegram.sent_texts(OWNER_TG)[-1]


async def test_the_same_update_is_handled_once(client: AsyncClient, telegram: FakeTelegram) -> None:
    body = {
        "update_id": 77,
        "message": {
            "message_id": 1,
            "chat": {"id": 5, "type": "private"},
            "from": {"id": 5},
            "text": "/start",
        },
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": webhook_secret()}
    for _ in range(2):
        assert (await client.post("/telegram/platform", json=body, headers=headers)).status_code == 200
    assert len(telegram.sent(5)) == 1


async def owner_store(db: AsyncSession, **dates: object) -> Tenant:
    owner = User(telegram_id=OWNER_TG, first_name="Doniyor")
    db.add(owner)
    await db.commit()
    tenant = await make_tenant(db, "varaq", owner, name="Varaq")
    if dates:
        await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(**dates))
        await db.commit()
    return tenant


async def test_reminders_go_out_once_per_period(db: AsyncSession, telegram: FakeTelegram) -> None:
    tenant = await owner_store(db, trial_ends_at=datetime.now(UTC) + timedelta(days=2))
    async with SessionLocal() as session:
        assert await subscriptions.scan_reminders(session) == 1
    async with SessionLocal() as session:
        assert await subscriptions.scan_reminders(session) == 0  # already sent
    await run_jobs()
    texts = telegram.sent_texts(OWNER_TG)
    assert len(texts) == 1
    assert "Varaq" in texts[0] and "bepul sinov muddati" in texts[0]
    assert "8600 1234 1234 1234" in texts[0] and "@javon_support" in texts[0]

    # The trial ends: the grace-days reminder, then the closing one.
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant.id)
        .values(trial_ends_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()
    async with SessionLocal() as session:
        assert await subscriptions.scan_reminders(session) == 1
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant.id)
        .values(trial_ends_at=datetime.now(UTC) - timedelta(days=5))
    )
    await db.commit()
    async with SessionLocal() as session:
        assert await subscriptions.scan_reminders(session) == 1
    await run_jobs()
    assert len(telegram.sent_texts(OWNER_TG)) == 2  # the grace reminder no longer applied: dropped
    assert "to'xtatildi" in telegram.sent_texts(OWNER_TG)[-1]


async def test_payment_notice_and_undeliverable_messages(
    client: AsyncClient, db: AsyncSession, telegram: FakeTelegram
) -> None:
    tenant = await owner_store(db)
    admin = await make_user(db, is_platform_admin=True)
    await sign_in(client, admin)
    await client.post(f"/system/tenants/{tenant.id}/subscription/payments", json={"plan": "pro", "months": 1})
    await run_jobs()
    assert "Pro" in telegram.sent_texts(OWNER_TG)[-1]

    # The owner never opened the bot: Telegram says 403; the job finishes quietly.
    telegram.fail("sendMessage", 403, "Forbidden: bot can't initiate conversation with a user")
    await client.post(f"/system/tenants/{tenant.id}/suspend", json={"reason": "Tekshiruv"})
    await run_jobs()
    statuses = await db.scalars(select(Job.status).where(Job.kind == "owner_notice"))
    assert set(statuses) == {"done"}

    # A network failure is retried later.
    telegram.fail("sendMessage", 502, "Bad Gateway")
    await client.post(f"/system/tenants/{tenant.id}/activate")
    await client.post(f"/system/tenants/{tenant.id}/suspend", json={"reason": "Yana"})
    await run_jobs()
    queued = await db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
    assert queued == 1


async def test_cleanup(db: AsyncSession, owner_engine: object) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    old = datetime.now(UTC) - timedelta(days=settings.CLEANUP_AFTER_DAYS + 1)
    db.add_all(
        [
            UserSession(user_id=owner.id, token_hash="a" * 64, expires_at=old),
            UserSession(
                user_id=owner.id, token_hash="b" * 64, expires_at=datetime.now(UTC) + timedelta(days=5)
            ),
            Job(kind="order_created", status="done", finished_at=old),
            Job(kind="order_created", status="failed", finished_at=old),
            StaffInvite(tenant_id=tenant.id, token_hash="c" * 64, expires_at=old),
            StaffInvite(
                tenant_id=tenant.id, token_hash="d" * 64, expires_at=datetime.now(UTC) + timedelta(days=5)
            ),
        ]
    )
    await db.commit()
    await db.execute(update(UserSession).values(updated_at=old).where(UserSession.token_hash == "a" * 64))
    await db.execute(update(StaffInvite).values(updated_at=old).where(StaffInvite.token_hash == "c" * 64))
    await db.commit()
    async with SessionLocal() as session:
        await bind_tenant(session, tenant.id)
        session.add(
            InventoryImport(
                tenant_id=tenant.id,
                created_by_user_id=owner.id,
                file_name="a.xlsx",
                file_data=b"xlsx",
                lang="uz",
                total_rows=1,
                status="done",
                finished_at=old,
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        removed = await subscriptions.cleanup(session)
    assert removed == {"sessions": 1, "jobs": 1, "invites": 1}
    async with SessionLocal() as session:
        await bind_tenant(session, tenant.id)
        assert await subscriptions.cleanup_store(session, tenant.id) == 1
        assert await session.scalar(select(InventoryImport.file_data)) is None
