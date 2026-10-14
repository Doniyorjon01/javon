"""
Store bots end to end, against the fake Telegram API: connecting, the staff
group, notifications from the outbox, buttons, Mini App buyers and card-transfer
receipts.
"""

import io
import itertools
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from redis.asyncio import Redis
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from config import settings
from database.config import SessionLocal, bind_tenant
from models import Customer, Job, JobStatus, MemberRole, Order, TelegramBot, Tenant, User
from services.storage import MemoryStorage
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in
from tests.fake_telegram import BOT_ID, BOT_USERNAME, TOKEN, FakeTelegram
from utils.signing import group_link_code
from utils.telegram_auth import sign_init_data
from workers import main as worker

pytestmark = pytest.mark.db

GROUP = -1001234567890
BUYER_TG = 555000111


@pytest.fixture(autouse=True)
async def clean_redis() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


async def run_jobs() -> None:
    while await worker.process_one():
        pass


def jpeg(size: tuple[int, int] = (600, 1200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, format="JPEG")
    return out.getvalue()


def init_data(user_id: int = BUYER_TG, *, token: str = TOKEN, age_s: int = 0) -> str:
    return sign_init_data(
        {
            "auth_date": str(int(time.time()) - age_s),
            "query_id": "AAH",
            "user": f'{{"id":{user_id},"first_name":"Aziz","language_code":"uz"}}',
        },
        token,
    )


class Shop:
    """A launched store with a book on the shelf and the bot connected."""

    def __init__(self, tenant: Tenant, owner: User, item_book_id: int) -> None:
        self.tenant = tenant
        self.owner = owner
        self.book_id = item_book_id

    async def secret(self, db: AsyncSession) -> str:
        return await db.scalar(
            select(TelegramBot.webhook_secret).where(TelegramBot.tenant_id == self.tenant.id),
            execution_options={"populate_existing": True},
        )


@pytest.fixture
async def shop(client: AsyncClient, db: AsyncSession) -> Shop:
    owner = await make_user(db, "Owner")
    tenant = await make_tenant(db, "varaq", owner)
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant.id)
        .values(card_transfer_enabled=True, card_number="8600123412341234", card_holder="Varaq MChJ")
    )
    await db.commit()
    item = await make_item(tenant, await make_book(db, "O'tkan kunlar"), price=4_500_000, quantity=5)
    await sign_in(client, owner)
    resp = await client.put(f"/tenants/{tenant.id}/telegram", json={"token": TOKEN})
    assert resp.status_code == 200, resp.text
    return Shop(tenant, owner, item.book_id)


_update_ids = itertools.count(1_000_000)  # above the ids tests set by hand


async def webhook(client: AsyncClient, db: AsyncSession, shop: Shop, update_body: dict[str, Any]) -> int:
    # A counter, not the clock: two updates in one millisecond would share an id and
    # the second would be dropped as a duplicate (the webhook handles each id once).
    update_body.setdefault("update_id", next(_update_ids))
    resp = await client.post(
        f"/telegram/webhook/{BOT_ID}",
        json=update_body,
        headers={"X-Telegram-Bot-Api-Secret-Token": await shop.secret(db)},
    )
    return resp.status_code


def group_message(text_value: str, sender_id: int, update_id: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "message": {
            "message_id": 1,
            "chat": {"id": GROUP, "type": "supergroup", "title": "Varaq xodimlari"},
            "from": {"id": sender_id, "first_name": "Ali"},
            "text": text_value,
        }
    }
    if update_id is not None:
        body["update_id"] = update_id
    return body


def private_message(**fields: Any) -> dict[str, Any]:
    return {
        "message": {
            "message_id": 50,
            "chat": {"id": BUYER_TG, "type": "private"},
            "from": {"id": BUYER_TG, "first_name": "Aziz", "language_code": "uz"},
            **fields,
        }
    }


def press(data: str, sender_id: int) -> dict[str, Any]:
    return {
        "callback_query": {
            "id": "cb1",
            "from": {"id": sender_id, "first_name": "Ali"},
            "data": data,
            "message": {"message_id": 9, "chat": {"id": GROUP, "type": "supergroup"}},
        }
    }


async def link_group(client: AsyncClient, db: AsyncSession, shop: Shop) -> None:
    code = group_link_code(shop.tenant.id)
    assert (
        await webhook(
            client, db, shop, group_message(f"/start@{BOT_USERNAME} {code}", shop.owner.telegram_id)
        )
        == 200
    )


def checkout(shop: Shop, **fields: Any) -> dict[str, Any]:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "customer_name": "Aziz Karimov",
        "phone": "+998901234567",
        "delivery_type": "pickup",
        "items": [{"book_id": shop.book_id, "quantity": 1}],
        **fields,
    }


async def order_row(order_id: int, tenant_id: int) -> Order:
    async with SessionLocal() as session:
        await bind_tenant(session, tenant_id)
        return await session.scalar(select(Order).where(Order.id == order_id))


# --------------------------------------------------------------------------- #
# Connecting
# --------------------------------------------------------------------------- #
async def test_connect_checks_the_token_and_configures_the_bot(
    client: AsyncClient, db: AsyncSession, telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_MODE", "webhook")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.javon.test")
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}/telegram"

    assert (await client.put(url, json={"token": "not a token at all......"})).status_code == 422
    telegram.fail("getMe", 401, "Unauthorized")
    refused = await client.put(url, json={"token": TOKEN})
    assert refused.json()["detail"]["code"] == "bot_token_invalid"
    telegram.heal("getMe")

    connected = await client.put(url, json={"token": TOKEN})
    assert connected.status_code == 200, connected.text
    body = connected.json()
    assert body["username"] == BOT_USERNAME and body["group_linked"] is False
    assert body["group_link_url"] == f"https://t.me/{BOT_USERNAME}?startgroup={group_link_code(tenant.id)}"
    assert "token" not in body

    webhook_call = next(c for c in telegram.calls if c.method == "setWebhook")
    assert webhook_call.params["url"] == f"https://api.javon.test/telegram/webhook/{BOT_ID}"
    row = await db.scalar(select(TelegramBot))
    assert webhook_call.params["secret_token"] == row.webhook_secret
    assert TOKEN.encode() not in row.token_encrypted  # encrypted at rest
    assert "setChatMenuButton" in telegram.methods()  # the Mini App button


async def test_bot_rules(client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram) -> None:
    staff = await make_user(db, "Staff")
    await add_member(db, shop.tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    assert (await client.get(f"/tenants/{shop.tenant.id}/telegram")).status_code == 403

    # One bot serves one store.
    other_owner = await make_user(db)
    other = await make_tenant(db, "boshqa", other_owner)
    await sign_in(client, other_owner)
    taken = await client.put(f"/tenants/{other.id}/telegram", json={"token": TOKEN})
    assert taken.json()["detail"]["code"] == "bot_in_use"

    # Updates with a wrong secret or for an unknown bot are refused.
    assert (await client.post(f"/telegram/webhook/{BOT_ID}", json={"update_id": 1})).status_code == 401
    assert (
        await client.post(
            "/telegram/webhook/123", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}
        )
    ).status_code == 401

    await sign_in(client, shop.owner)
    assert (await client.delete(f"/tenants/{shop.tenant.id}/telegram")).status_code == 204
    assert (await client.get(f"/tenants/{shop.tenant.id}/telegram")).status_code == 404


# --------------------------------------------------------------------------- #
# The staff group
# --------------------------------------------------------------------------- #
async def test_only_staff_can_link_the_group(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    code = group_link_code(shop.tenant.id)
    await webhook(client, db, shop, group_message(f"/start {code}", sender_id=424242))  # a stranger
    assert await db.scalar(select(TelegramBot.group_chat_id)) is None
    assert "faqat" in telegram.sent_texts(GROUP)[-1]

    await webhook(client, db, shop, group_message("/start g1_forged", shop.owner.telegram_id))
    assert await db.scalar(select(TelegramBot.group_chat_id)) is None

    await link_group(client, db, shop)
    row = await db.scalar(select(TelegramBot), execution_options={"populate_existing": True})
    assert (row.group_chat_id, row.group_title) == (GROUP, "Varaq xodimlari")
    assert "ulandi" in telegram.sent_texts(GROUP)[-1]

    await sign_in(client, shop.owner)
    assert (await client.post(f"/tenants/{shop.tenant.id}/telegram/test")).status_code == 204

    # Bot removed from the group: the link is cleared.
    removed = {"my_chat_member": {"chat": {"id": GROUP}, "new_chat_member": {"status": "kicked"}}}
    await webhook(client, db, shop, removed)
    assert (
        await db.scalar(select(TelegramBot.group_chat_id), execution_options={"populate_existing": True})
        is None
    )


async def test_an_update_is_handled_once(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    body = group_message(f"/start {group_link_code(shop.tenant.id)}", shop.owner.telegram_id, update_id=99)
    await webhook(client, db, shop, dict(body))
    await webhook(client, db, shop, dict(body))
    assert len(telegram.sent(GROUP)) == 1


# --------------------------------------------------------------------------- #
# Orders in the group, and its buttons
# --------------------------------------------------------------------------- #
async def test_new_order_reaches_the_group_and_can_be_accepted_there(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    await link_group(client, db, shop)
    order = (await client.post("/storefront/varaq/orders", json=checkout(shop))).json()
    await run_jobs()

    message = telegram.sent(GROUP)[-1]
    assert f"#{order['number']}" in message.params["text"]
    assert "+998901234567" not in message.params["text"]  # no buyer phone on Telegram by default
    assert "Aziz" in message.params["text"] and "Karimov" not in message.params["text"]
    buttons = [b for row in message.params["reply_markup"]["inline_keyboard"] for b in row]
    assert {"text": "✅ Qabul qilish", "callback_data": f"acc:{order['id']}"} in buttons

    # A stranger in the group cannot press it.
    await webhook(client, db, shop, press(f"acc:{order['id']}", sender_id=424242))
    assert (await order_row(order["id"], shop.tenant.id)).status == "new"
    assert telegram.calls[-1].method == "answerCallbackQuery" and telegram.calls[-1].params["show_alert"]

    await webhook(client, db, shop, press(f"acc:{order['id']}", sender_id=shop.owner.telegram_id))
    assert (await order_row(order["id"], shop.tenant.id)).status == "accepted"
    assert "editMessageReplyMarkup" in telegram.methods()
    # Pressing again: the order already moved on.
    await webhook(client, db, shop, press(f"acc:{order['id']}", sender_id=shop.owner.telegram_id))
    assert "allaqachon" in telegram.calls[-1].params["text"]


async def test_notification_failures(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    await link_group(client, db, shop)

    telegram.fail("sendMessage", 429, "Too Many Requests: retry after 5", {"retry_after": 5})
    await client.post("/storefront/varaq/orders", json=checkout(shop))
    await run_jobs()
    job = await db.scalar(select(Job), execution_options={"populate_existing": True})
    assert job.status == JobStatus.QUEUED and job.attempts == 1  # will be retried

    telegram.fail("sendMessage", 400, "Bad Request: group chat was upgraded", {"migrate_to_chat_id": -100777})
    await db.execute(update(Job).values(run_after=text("now()")))
    await db.commit()
    await worker.process_one()
    # The first send failed with the migration; the second went to the new id (and failed
    # the same way in this fake, which is fine): the stored group id followed.
    assert (
        await db.scalar(select(TelegramBot.group_chat_id), execution_options={"populate_existing": True})
        == -100777
    )

    telegram.fail("sendMessage", 401, "Unauthorized")
    await client.post("/storefront/varaq/orders", json=checkout(shop))
    await run_jobs()
    assert (
        await db.scalar(select(TelegramBot.status), execution_options={"populate_existing": True}) == "broken"
    )


# --------------------------------------------------------------------------- #
# Mini App buyers
# --------------------------------------------------------------------------- #
async def test_mini_app_order_and_status_messages(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    headers = {"X-Telegram-Init-Data": init_data()}
    resp = await client.post("/storefront/varaq/orders", json=checkout(shop), headers=headers)
    assert resp.status_code == 201, resp.text
    order = resp.json()
    row = await order_row(order["id"], shop.tenant.id)
    assert row.channel == "telegram"
    async with SessionLocal() as session:
        await bind_tenant(session, shop.tenant.id)
        assert await session.scalar(select(Customer.telegram_id)) == BUYER_TG

    await run_jobs()
    assert f"#{order['number']}" in telegram.sent_texts(BUYER_TG)[-1]

    await sign_in(client, shop.owner)
    await client.post(f"/tenants/{shop.tenant.id}/orders/{order['id']}/status", json={"status": "accepted"})
    await run_jobs()
    assert "qabul qilindi" in telegram.sent_texts(BUYER_TG)[-1]

    mine = await client.get("/storefront/varaq/telegram/orders", headers=headers)
    assert [o["id"] for o in mine.json()] == [order["id"]]
    assert mine.json()[0]["tracking_token"] == order["tracking_token"]


@pytest.mark.parametrize(
    "header",
    [
        lambda: init_data(token="111:wrong-token"),  # signed by another bot
        lambda: init_data(age_s=3 * 86_400),  # too old
        lambda: init_data() + "x",  # tampered
    ],
)
async def test_bad_init_data_is_refused(client: AsyncClient, shop: Shop, header: Any) -> None:
    resp = await client.post(
        "/storefront/varaq/orders", json=checkout(shop), headers={"X-Telegram-Init-Data": header()}
    )
    assert resp.status_code == 401
    assert (await client.get("/storefront/varaq/telegram/orders")).status_code == 401


async def test_web_buyer_links_the_order_to_telegram(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    order = (await client.post("/storefront/varaq/orders", json=checkout(shop))).json()
    link = order["telegram_link"]
    assert link.startswith(f"https://t.me/{BOT_USERNAME}?start=o{order['id']}_")
    code = link.split("start=")[1]

    await webhook(client, db, shop, private_message(text=f"/start {code}"))
    assert "kuzatil" in telegram.sent_texts(BUYER_TG)[-1] or "yuboriladi" in telegram.sent_texts(BUYER_TG)[-1]
    async with SessionLocal() as session:
        await bind_tenant(session, shop.tenant.id)
        assert await session.scalar(select(Customer.telegram_id)) == BUYER_TG

    # A forged code only gets the welcome message.
    await webhook(client, db, shop, private_message(text=f"/start o{order['id']}_forgedtoken"))
    assert "xush kelibsiz" in telegram.sent_texts(BUYER_TG)[-1]


# --------------------------------------------------------------------------- #
# Card transfer
# --------------------------------------------------------------------------- #
async def test_card_transfer_with_receipt_in_telegram(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram, private_storage: MemoryStorage
) -> None:
    await link_group(client, db, shop)
    headers = {"X-Telegram-Init-Data": init_data()}
    order = (
        await client.post(
            "/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"), headers=headers
        )
    ).json()
    assert order["card_transfer"] == {
        "card_number": "8600123412341234",
        "card_holder": "Varaq MChJ",
        "amount": 4_500_000,
        "hold_hours": settings.CARD_TRANSFER_HOLD_HOURS,
    }
    await run_jobs()
    assert "8600 1234 1234 1234" in telegram.sent_texts(BUYER_TG)[-1]  # payment instructions

    telegram.files["photo-1"] = jpeg()
    photo = [{"file_id": "photo-small", "width": 90}, {"file_id": "photo-1", "width": 600}]
    await webhook(client, db, shop, private_message(photo=photo))
    assert "qabul qilindi" in telegram.sent_texts(BUYER_TG)[-1]
    assert (await order_row(order["id"], shop.tenant.id)).payment_status == "under_review"
    assert len(private_storage.objects) == 1

    await run_jobs()
    copy = next(c for c in telegram.calls if c.method == "copyMessage")
    assert (copy.params["chat_id"], copy.params["from_chat_id"]) == (GROUP, BUYER_TG)
    review = telegram.sent(GROUP)[-1]
    buttons = [b["callback_data"] for row in review.params["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == [f"pok:{order['id']}", f"pno:{order['id']}"]

    # Wrong receipt: back to unpaid, the buyer is told why and sends another.
    await webhook(client, db, shop, press(f"pno:{order['id']}", shop.owner.telegram_id))
    row = await order_row(order["id"], shop.tenant.id)
    assert (row.payment_status, row.payment_note) == ("unpaid", "Chek tasdiqlanmadi")
    await run_jobs()
    assert "tasdiqlanmadi" in telegram.sent_texts(BUYER_TG)[-1]

    telegram.files["photo-2"] = jpeg((700, 1400))
    await webhook(client, db, shop, private_message(photo=[{"file_id": "photo-2"}], message_id=51))
    assert len(private_storage.objects) == 1  # the refused receipt was replaced, not kept
    await webhook(client, db, shop, press(f"pok:{order['id']}", shop.owner.telegram_id))
    row = await order_row(order["id"], shop.tenant.id)
    assert row.payment_status == "paid" and row.paid_at is not None
    await run_jobs()
    assert "tasdiqlandi" in telegram.sent_texts(BUYER_TG)[-1]

    await sign_in(client, shop.owner)
    done = await client.post(
        f"/tenants/{shop.tenant.id}/orders/{order['id']}/status", json={"status": "accepted"}
    )
    assert done.status_code == 200
    done = await client.post(
        f"/tenants/{shop.tenant.id}/orders/{order['id']}/status", json={"status": "completed"}
    )
    assert done.json()["status"] == "completed"


async def test_card_transfer_with_receipt_on_the_website(
    client: AsyncClient, db: AsyncSession, shop: Shop, private_storage: MemoryStorage
) -> None:
    order = (
        await client.post("/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"))
    ).json()
    url = f"/storefront/varaq/orders/{order['id']}/payment-proof"
    files = {"file": ("chek.jpg", jpeg(), "image/jpeg")}
    assert (await client.post(url, params={"token": "x" * 22}, files=files)).status_code == 404
    uploaded = await client.post(url, params={"token": order["tracking_token"]}, files=files)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["payment_status"] == "under_review"

    await sign_in(client, shop.owner)
    admin = f"/tenants/{shop.tenant.id}/orders/{order['id']}"
    assert (await client.get(admin)).json()["has_payment_proof"] is True
    picture = await client.get(f"{admin}/payment-proof")
    assert picture.headers["content-type"] == "image/webp"
    assert picture.headers["cache-control"] == "private, no-store"

    # Not paid yet: cannot be completed.
    await client.post(f"{admin}/status", json={"status": "accepted"})
    blocked = await client.post(f"{admin}/status", json={"status": "completed"})
    assert blocked.json()["detail"]["code"] == "order_not_paid"
    assert (
        await client.post(f"{admin}/payment", json={"approve": False})
    ).status_code == 422  # reason needed
    approved = await client.post(f"{admin}/payment", json={"approve": True})
    assert approved.json()["payment_status"] == "paid"
    assert (await client.post(f"{admin}/status", json={"status": "completed"})).status_code == 200

    # A cash order has no receipt to upload.
    cash = (await client.post("/storefront/varaq/orders", json=checkout(shop))).json()
    refused = await client.post(
        f"/storefront/varaq/orders/{cash['id']}/payment-proof",
        params={"token": cash["tracking_token"]},
        files=files,
    )
    assert refused.json()["detail"]["code"] == "payment_proof_not_expected"


async def test_unpaid_card_orders_are_cancelled_after_the_hold(
    client: AsyncClient, db: AsyncSession, shop: Shop, owner_engine: AsyncEngine
) -> None:
    late = (
        await client.post("/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"))
    ).json()
    sent = (
        await client.post("/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"))
    ).json()
    await client.post(
        f"/storefront/varaq/orders/{sent['id']}/payment-proof",
        params={"token": sent["tracking_token"]},
        files={"file": ("c.jpg", jpeg(), "image/jpeg")},
    )
    fresh = (
        await client.post("/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"))
    ).json()
    refused = (
        await client.post("/storefront/varaq/orders", json=checkout(shop, payment_method="card_transfer"))
    ).json()
    await client.post(
        f"/storefront/varaq/orders/{refused['id']}/payment-proof",
        params={"token": refused["tracking_token"]},
        files={"file": ("c.jpg", jpeg(), "image/jpeg")},
    )
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE orders SET created_at = now() - interval '25 hours', "
                "updated_at = now() - interval '25 hours' WHERE id = ANY(:ids)"
            ),
            {"ids": [late["id"], sent["id"], refused["id"]]},
        )
    # The receipt is refused 25 hours after the order: the buyer gets a new hold.
    await sign_in(client, shop.owner)
    review = await client.post(
        f"/tenants/{shop.tenant.id}/orders/{refused['id']}/payment",
        json={"approve": False, "note": "Summa boshqa"},
    )
    assert review.status_code == 200

    await worker.run_periodic_tasks()
    assert (await order_row(late["id"], shop.tenant.id)).status == "cancelled"
    assert (await order_row(sent["id"], shop.tenant.id)).status == "new"  # receipt under review
    assert (await order_row(fresh["id"], shop.tenant.id)).status == "new"
    assert (await order_row(refused["id"], shop.tenant.id)).status == "new"
    assert (await order_row(late["id"], shop.tenant.id)).cancel_reason


async def test_receipt_without_an_unpaid_order(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    telegram.files["p"] = jpeg()
    await webhook(client, db, shop, private_message(photo=[{"file_id": "p"}]))
    assert "topilmadi" in telegram.sent_texts(BUYER_TG)[-1]


# --------------------------------------------------------------------------- #
# Payment settings
# --------------------------------------------------------------------------- #
async def test_payment_settings(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    book = await make_book(db)
    await make_item(tenant, book)
    await sign_in(client, owner)
    url = f"/tenants/{tenant.id}"

    no_card = await client.patch(url, json={"card_transfer_enabled": True})
    assert no_card.json()["detail"]["code"] == "card_details_required"
    nothing = await client.patch(url, json={"cash_enabled": False})
    assert nothing.json()["detail"]["code"] == "payment_option_required"
    assert (await client.patch(url, json={"card_number": "8600 12"})).status_code == 422

    ok = await client.patch(
        url,
        json={
            "card_transfer_enabled": True,
            "card_number": "8600 1234-1234 1234",
            "card_holder": "Ali Valiyev",
        },
    )
    assert ok.json()["card_number"] == "8600123412341234"
    public = (await client.get("/storefront/varaq")).json()
    assert public["card_transfer_enabled"] is True and "card_number" not in public

    await client.patch(url, json={"card_transfer_enabled": False})
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "customer_name": "Aziz",
        "phone": "901234567",
        "delivery_type": "pickup",
        "payment_method": "card_transfer",
        "items": [{"book_id": book.id, "quantity": 1}],
    }
    refused = await client.post("/storefront/varaq/orders", json=body)
    assert refused.json()["detail"]["code"] == "payment_method_unavailable"


# --------------------------------------------------------------------------- #
# A closed store (unpaid past the grace days, or suspended)
# --------------------------------------------------------------------------- #
async def test_closed_store_buttons_and_welcome(
    client: AsyncClient, db: AsyncSession, shop: Shop, telegram: FakeTelegram
) -> None:
    await link_group(client, db, shop)
    resp = await client.post("/storefront/varaq/orders", json=checkout(shop))
    order_id = resp.json()["id"]
    await db.execute(
        update(Tenant)
        .where(Tenant.id == shop.tenant.id)
        .values(trial_ends_at=func.now() - text("interval '10 days'"))
    )
    await db.commit()

    assert await webhook(client, db, shop, press(f"acc:{order_id}", shop.owner.telegram_id)) == 200
    answer = [c for c in telegram.calls if c.method == "answerCallbackQuery"][-1]
    assert "obunasi to'xtagan" in answer.params["text"]
    assert (await order_row(order_id, shop.tenant.id)).status == "new"

    assert await webhook(client, db, shop, private_message(text="/start")) == 200
    assert "buyurtma qabul qilmayapti" in telegram.sent_texts(BUYER_TG)[-1]
