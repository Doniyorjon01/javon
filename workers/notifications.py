"""
Order and payment notifications (outbox jobs)
=============================================
Jobs written by db_order in the same transaction as the change they announce.
Each one sends at most two messages through the store's own bot:

  * to the store's Telegram group (if linked): new order with an "accept"
    button; a payment receipt with "payment received / wrong receipt" buttons;
  * to the buyer (if their Telegram chat is known): status changes, payment
    confirmed or refused, payment instructions.

Failures: a network error or Telegram overload (429, 5xx) on the GROUP message
raises, so the job is retried with backoff. A buyer message is best effort (a
retry would repeat the group message). Permanent refusals are not retried: a
revoked token marks the bot broken, a bot removed from the group or blocked by
the buyer is only logged. A group upgraded to a supergroup gets its new id and
the message is sent again.

Personal data: by default the group message carries the buyer's first name only
(settings.TELEGRAM_ORDER_CONTACTS); phone and address stay in our panel.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_order, db_telegram, db_tenant
from models.job import Job
from models.order import DeliveryType, Order, OrderChannel, OrderStatus, PaymentMethod, PaymentStatus
from models.telegram import BotStatus
from services.telegram import TelegramClient, TelegramError, callback_button, inline_keyboard, url_button
from services.telegram_texts import raw, text
from services.telegram_updates import (
    ACCEPT,
    PAY_NO,
    PAY_OK,
    BotInfo,
    StoreInfo,
    callback_data,
    payment_instructions,
)
from utils.money import format_som

logger = logging.getLogger(__name__)

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """One Telegram client per worker process (tests replace it with set_client)."""
    global _client
    if _client is None:
        _client = TelegramClient()
    return _client


def set_client(client: TelegramClient | None) -> None:
    global _client
    _client = client


class _Target:
    """Where a job's messages go; loaded fresh for every job."""

    def __init__(
        self, store: StoreInfo, bot: BotInfo | None, order: Order, buyer_chat_id: int | None
    ) -> None:
        self.store = store
        self.bot = bot
        self.order = order
        self.buyer_chat_id = buyer_chat_id


async def _target(db: AsyncSession, job: Job) -> _Target | None:
    tenant_id = job.tenant_id
    if tenant_id is None:
        return None
    tenant = await db_tenant.get_tenant(db, tenant_id)
    bot_row = await db_telegram.get_bot(db, tenant_id)
    bot = BotInfo.of(bot_row) if bot_row is not None and bot_row.status == BotStatus.ACTIVE else None
    order = await db_order.get_order(db, tenant_id, int(job.payload["order_id"]))
    buyer_chat_id = await db_order.get_buyer_telegram_id(db, tenant_id, order)
    return _Target(StoreInfo.of(tenant), bot, order, buyer_chat_id)


def _panel_button(target: _Target) -> dict[str, Any] | None:
    url = f"{settings.ADMIN_PANEL_URL.rstrip('/')}/{target.store.id}/orders/{target.order.id}"
    return url_button(text("btn_open", target.store.lang), url)


async def _send(
    db: AsyncSession,
    target: _Target,
    chat_id: int,
    message: str,
    markup: dict[str, Any] | None = None,
    *,
    group: bool,
) -> bool:
    """True if sent. Raises for errors worth a retry (group messages only)."""
    if target.bot is None:
        return False
    client = get_client()
    try:
        await client.send_message(target.bot.token, chat_id, message, markup)
        return True
    except TelegramError as exc:
        log = {"tenant_id": target.store.id, "order_id": target.order.id, "code": exc.code, "group": group}
        if group and exc.migrate_to_chat_id:
            await db_telegram.set_group(db, target.bot.id, int(exc.migrate_to_chat_id), None)
            await client.send_message(target.bot.token, int(exc.migrate_to_chat_id), message, markup)
            return True
        if exc.code == 401:
            await db_telegram.mark_broken(db, target.bot.id, exc.description)
            return False
        if exc.code in (400, 403):  # chat gone, bot removed or blocked: retrying will not help
            logger.info("Telegram refused a notification", extra=log)
            return False
        if group:
            raise
        logger.warning("Buyer notification failed", extra=log)
        return False


def _group_chat(target: _Target) -> int | None:
    return target.bot.group_chat_id if target.bot else None


def _order_lines(order: Order, lang: Any) -> str:
    return "\n".join(
        text(
            "order_line",
            lang,
            title=item.title,
            quantity=item.quantity,
            amount=format_som(item.line_total, lang),
        )
        for item in order.items
    )


async def order_created(db: AsyncSession, job: Job) -> None:
    target = await _target(db, job)
    if target is None or target.bot is None:
        return
    order, store, lang = target.order, target.store, target.store.lang

    group = _group_chat(target)
    if group is not None:
        contacts = ""
        if settings.TELEGRAM_ORDER_CONTACTS:
            contacts = text("order_contacts", lang, phone=order.customer_phone, address=order.address or "-")
        message = text(
            "group_new_order",
            lang,
            number=order.number,
            lines=raw(_order_lines(order, lang)),
            total=format_som(order.total, lang),
            delivery=text(f"delivery_{order.delivery_type.value}", lang),
            payment=text(f"payment_{order.payment_method.value}", lang),
            name=order.customer_name.split()[0] if order.customer_name else "",
            contacts=raw(contacts),
        )
        buttons = inline_keyboard(
            [callback_button(text("btn_accept", lang), callback_data(ACCEPT, order.id))]
            if order.status == OrderStatus.NEW
            else [],
            [b for b in [_panel_button(target)] if b],
        )
        await _send(db, target, group, message, buttons, group=True)

    if target.buyer_chat_id is not None and order.channel == OrderChannel.TELEGRAM:
        await _send(
            db,
            target,
            target.buyer_chat_id,
            text("buyer_order_created", lang, number=order.number, total=format_som(order.total, lang)),
            group=False,
        )
        if (
            order.payment_method == PaymentMethod.CARD_TRANSFER
            and order.payment_status == PaymentStatus.UNPAID
        ):
            await _send(
                db, target, target.buyer_chat_id, payment_instructions(store, order.total, lang), group=False
            )


async def order_status_changed(db: AsyncSession, job: Job) -> None:
    target = await _target(db, job)
    if target is None or target.bot is None or target.buyer_chat_id is None:
        return
    new_status = job.payload.get("status")
    if new_status not in ("accepted", "shipping", "completed", "cancelled"):
        return
    if new_status == "shipping" and target.order.delivery_type != DeliveryType.DELIVERY:
        return
    lang = target.store.lang
    values: dict[str, object] = {"number": target.order.number}
    if new_status == "cancelled":
        values["reason"] = target.order.cancel_reason or ""
    await _send(
        db, target, target.buyer_chat_id, text(f"buyer_status_{new_status}", lang, **values), group=False
    )


async def payment_proof_received(db: AsyncSession, job: Job) -> None:
    target = await _target(db, job)
    if target is None or target.bot is None:
        return
    group = _group_chat(target)
    if group is None:
        return
    order, lang = target.order, target.store.lang
    review_buttons = [
        callback_button(text("btn_pay_ok", lang), callback_data(PAY_OK, order.id)),
        callback_button(text("btn_pay_no", lang), callback_data(PAY_NO, order.id)),
    ]
    total = format_som(order.total, lang)
    chat_id, message_id = job.payload.get("chat_id"), job.payload.get("message_id")
    if chat_id is not None and message_id is not None:
        # Sent to the bot: show the store the picture itself (it is already on Telegram).
        try:
            await get_client().copy_message(target.bot.token, group, int(chat_id), int(message_id))
        except TelegramError as exc:
            logger.info("Could not copy the receipt to the group", extra={"code": exc.code})
        message = text("group_receipt", lang, number=order.number, total=total)
        markup = inline_keyboard(review_buttons)
    else:
        # Uploaded on the website: the picture stays on our server; staff open it in the panel.
        message = text("group_receipt_web", lang, number=order.number, total=total)
        markup = inline_keyboard(review_buttons, [b for b in [_panel_button(target)] if b])
    await _send(db, target, group, message, markup, group=True)


async def payment_reviewed(db: AsyncSession, job: Job) -> None:
    target = await _target(db, job)
    if target is None or target.bot is None or target.buyer_chat_id is None:
        return
    order, lang = target.order, target.store.lang
    if job.payload.get("approved"):
        message = text("buyer_payment_confirmed", lang, number=order.number)
    else:
        message = text("buyer_payment_refused", lang, number=order.number, reason=order.payment_note or "-")
    await _send(db, target, target.buyer_chat_id, message, group=False)
