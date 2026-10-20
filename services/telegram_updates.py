"""
What a store's bot does with incoming updates
=============================================
One entry point, handle_update(), used by the webhook route and by the local
polling script. The session is already bound to the bot's store (RLS).

Private chat with a buyer:
    /start                    welcome + "open the store" (Mini App) button
    /start o<id>_<token>      a web buyer links their order: updates come here
    photo / image document    the payment receipt for their latest unpaid
                              card-transfer order -> stored privately,
                              order -> under_review, the store's group is told
    anything else             a short help text

The store's group:
    /start g<tenant>_<sig>    (sent by Telegram when the bot is added with the
                              "add to group" link) links the group, if the person
                              who added it works in the store
    button presses            accept an order, confirm or refuse a receipt —
                              only for the store's owner and staff (matched by
                              their Telegram id: they signed in with Telegram)
    group upgraded / bot removed  the stored group id follows or is cleared

Telegram retries an update it did not get a 200 for; the webhook route makes
handling at-most-once with a Redis key per update.
"""

import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_order, db_telegram
from models.order import OrderStatus, PaymentMethod, PaymentStatus
from models.telegram import TelegramBot
from models.tenant import Tenant
from services.media import delete_image, save_image
from services.storage import Storage
from services.telegram import (
    TelegramClient,
    TelegramError,
    inline_keyboard,
    web_app_button,
)
from services.telegram_texts import pick_lang, text
from utils.i18n import Lang
from utils.images import RECEIPT_SPEC
from utils.money import format_som
from utils.plans import CLOSED_STATES, access_state
from utils.signing import parse_group_link_code, parse_order_start_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoreInfo:
    """Plain values copied from the store's row: the handlers roll back and commit
    along the way, and an expired ORM object cannot be reloaded lazily in async."""

    id: int
    name: str
    slug: str
    card_number: str | None
    card_holder: str | None
    lang: Lang  # the store's language: its group and unknown buyers
    # Unpaid past the grace days or suspended: the group's buttons change nothing
    # and buyers are told the store is closed (same rule as the admin panel).
    closed: bool = False
    launched: bool = True

    @classmethod
    def of(cls, tenant: Tenant) -> "StoreInfo":
        state = access_state(tenant.status, tenant.trial_ends_at, tenant.paid_until, datetime.now(UTC))
        return cls(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            card_number=tenant.card_number,
            card_holder=tenant.card_holder,
            lang=db_telegram.store_lang(tenant),
            closed=state in CLOSED_STATES,
            launched=tenant.launched_at is not None and tenant.paused_at is None,
        )


@dataclass(frozen=True, slots=True)
class BotInfo:
    id: int  # our row id
    token: str
    group_chat_id: int | None

    @classmethod
    def of(cls, bot: TelegramBot) -> "BotInfo":
        return cls(id=bot.id, token=db_telegram.bot_token(bot), group_chat_id=bot.group_chat_id)


@dataclass
class BotContext:
    db: AsyncSession  # bound to the bot's store
    client: TelegramClient
    private_storage: Storage | None
    bot: BotInfo
    store: StoreInfo

    @property
    def token(self) -> str:
        return self.bot.token

    @property
    def lang(self) -> Lang:
        return self.store.lang

    async def send(self, chat_id: int, message: str, markup: dict[str, Any] | None = None) -> None:
        try:
            await self.client.send_message(self.token, chat_id, message, markup)
        except TelegramError as exc:
            logger.info(
                "Bot could not send a reply",
                extra={"tenant_id": self.store.id, "method": exc.method, "code": exc.code},
            )


def _start_param(message_text: str) -> str | None:
    """ "/start abc" and "/start@SomeBot abc" -> "abc"; plain "/start" -> ""; other -> None."""
    command, _, rest = message_text.strip().partition(" ")
    if command.split("@")[0] != "/start":
        return None
    return rest.strip()


async def handle_update(ctx: BotContext, update: dict[str, Any]) -> None:
    if "message" in update:
        await _on_message(ctx, update["message"])
    elif "callback_query" in update:
        await _on_callback(ctx, update["callback_query"])
    elif "my_chat_member" in update:
        await _on_membership(ctx, update["my_chat_member"])


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
async def _on_message(ctx: BotContext, message: dict[str, Any]) -> None:
    chat = message.get("chat", {})
    sender = message.get("from", {})
    if chat.get("type") in ("group", "supergroup"):
        await _on_group_message(ctx, message, chat, sender)
    elif chat.get("type") == "private" and sender.get("id"):
        await _on_private_message(ctx, message, chat, sender)


async def _on_group_message(ctx: BotContext, message: dict[str, Any], chat: dict, sender: dict) -> None:
    if "migrate_to_chat_id" in message and chat.get("id") == ctx.bot.group_chat_id:
        await db_telegram.set_group(ctx.db, ctx.bot.id, int(message["migrate_to_chat_id"]), chat.get("title"))
        return
    param = _start_param(message.get("text", ""))
    if not param or parse_group_link_code(param) != ctx.store.id:
        return
    role = await db_telegram.get_member_role_by_telegram(ctx.db, ctx.store.id, int(sender.get("id", 0)))
    if role is None:
        await ctx.send(chat["id"], text("group_link_denied", ctx.lang))
        return
    await db_telegram.set_group(ctx.db, ctx.bot.id, int(chat["id"]), chat.get("title"))
    logger.info("Store group linked", extra={"tenant_id": ctx.store.id})
    await ctx.send(chat["id"], text("group_linked", ctx.lang, store=ctx.store.name))


def _store_button(ctx: BotContext, lang: Lang) -> dict[str, Any] | None:
    button = web_app_button(text("btn_open_store", lang), db_telegram.mini_app_url(ctx.store.slug))
    return inline_keyboard([button]) if button else None


async def _on_private_message(ctx: BotContext, message: dict[str, Any], chat: dict, sender: dict) -> None:
    lang = pick_lang(sender.get("language_code"), ctx.lang)
    chat_id = int(chat["id"])
    user_id = int(sender["id"])

    param = _start_param(message.get("text", ""))
    if param is not None:
        order_id = parse_order_start_code(ctx.store.id, param) if param else None
        if order_id is None and (ctx.store.closed or not ctx.store.launched):
            await ctx.send(chat_id, text("buyer_store_closed", lang, store=ctx.store.name))
            return
        if order_id is None:
            await ctx.send(
                chat_id, text("buyer_welcome", lang, store=ctx.store.name), _store_button(ctx, lang)
            )
            return
        order = await db_order.link_telegram_buyer(ctx.db, ctx.store.id, order_id, user_id, lang)
        await ctx.send(chat_id, text("buyer_order_linked", lang, number=order.number))
        if (
            order.payment_method == PaymentMethod.CARD_TRANSFER
            and order.payment_status == PaymentStatus.UNPAID
        ):
            await ctx.send(chat_id, payment_instructions(ctx.store, order.total, lang))
        return

    file_id = _receipt_file_id(message)
    if file_id is not None:
        await _on_receipt(ctx, message, chat_id, user_id, file_id, lang)
        return
    if message.get("document") is not None:
        await ctx.send(chat_id, text("buyer_bad_receipt_file", lang))
        return
    await ctx.send(chat_id, text("buyer_help", lang), _store_button(ctx, lang))


def _receipt_file_id(message: dict[str, Any]) -> str | None:
    if message.get("photo"):
        return message["photo"][-1]["file_id"]  # the largest size
    document = message.get("document") or {}
    if str(document.get("mime_type", "")).startswith("image/"):
        return document.get("file_id")
    return None


def payment_instructions(store: StoreInfo, total: int, lang: Lang) -> str:
    card = store.card_number or ""
    spaced = " ".join(card[i : i + 4] for i in range(0, len(card), 4))
    return text(
        "buyer_pay_instructions",
        lang,
        total=format_som(total, lang),
        card=spaced,
        holder=store.card_holder or "",
        hours=settings.CARD_TRANSFER_HOLD_HOURS,
    )


async def _on_receipt(
    ctx: BotContext, message: dict[str, Any], chat_id: int, user_id: int, file_id: str, lang: Lang
) -> None:
    order = await db_order.find_order_awaiting_proof(ctx.db, ctx.store.id, user_id)
    if order is None or ctx.private_storage is None:
        await ctx.send(chat_id, text("buyer_no_unpaid_order", lang))
        return
    order_id = order.id
    await ctx.db.rollback()  # no transaction open while we download and convert
    try:
        data = await ctx.client.download_file(ctx.token, file_id)
        key = await save_image(
            ctx.private_storage, f"receipts/{ctx.store.id}/{order_id}", data, RECEIPT_SPEC, lang
        )
    except (TelegramError, HTTPException):
        await ctx.send(chat_id, text("buyer_bad_receipt_file", lang))
        return
    try:
        order, replaced = await db_order.attach_payment_proof(
            ctx.db, ctx.store.id, order_id, key, lang, telegram_message=(chat_id, int(message["message_id"]))
        )
    except HTTPException:  # paid or cancelled in the meantime
        await delete_image(ctx.private_storage, key, RECEIPT_SPEC)
        await ctx.send(chat_id, text("buyer_no_unpaid_order", lang))
        return
    await delete_image(ctx.private_storage, replaced, RECEIPT_SPEC)
    await ctx.send(chat_id, text("buyer_receipt_received", lang, number=order.number))


# --------------------------------------------------------------------------- #
# Buttons in the store's group
# --------------------------------------------------------------------------- #
ACCEPT = "acc"
PAY_OK = "pok"
PAY_NO = "pno"


def callback_data(action: str, order_id: int) -> str:
    return f"{action}:{order_id}"


async def _on_callback(ctx: BotContext, query: dict[str, Any]) -> None:
    sender = query.get("from", {})
    action, _, order_part = str(query.get("data", "")).partition(":")
    message = query.get("message") or {}
    if action not in (ACCEPT, PAY_OK, PAY_NO) or not order_part.isdigit():
        return
    order_id = int(order_part)
    lang = ctx.lang

    role = await db_telegram.get_member_role_by_telegram(ctx.db, ctx.store.id, int(sender.get("id", 0)))
    if role is None:
        await _answer(ctx, query, text("cb_not_member", lang), alert=True)
        return
    if ctx.store.closed:
        await _answer(ctx, query, text("cb_store_closed", lang), alert=True)
        return

    try:
        if action == ACCEPT:
            order = await db_order.change_status(
                ctx.db, ctx.store.id, order_id, OrderStatus.ACCEPTED, None, lang
            )
            note_key = "group_order_accepted"
        else:
            approve = action == PAY_OK
            refusal = None if approve else text("receipt_refused_note", lang)
            order = await db_order.review_payment(ctx.db, ctx.store.id, order_id, approve, refusal, lang)
            note_key = "group_payment_done" if approve else "group_payment_refused"
    except HTTPException:
        await _answer(ctx, query, text("cb_stale", lang))
        return

    await _answer(ctx, query, text("cb_done", lang))
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is not None and message.get("message_id") is not None:
        # An old message whose buttons cannot be edited any more is harmless.
        with contextlib.suppress(TelegramError):
            await ctx.client.edit_reply_markup(ctx.token, int(chat_id), int(message["message_id"]))
        await ctx.send(
            int(chat_id), text(note_key, lang, number=order.number, who=sender.get("first_name", "")[:64])
        )


async def _answer(ctx: BotContext, query: dict[str, Any], message: str, alert: bool = False) -> None:
    with contextlib.suppress(TelegramError):  # the button's spinner times out on its own
        await ctx.client.answer_callback(ctx.token, str(query["id"]), message, alert)


# --------------------------------------------------------------------------- #
# The bot's own membership in a chat
# --------------------------------------------------------------------------- #
async def _on_membership(ctx: BotContext, change: dict[str, Any]) -> None:
    chat_id = (change.get("chat") or {}).get("id")
    new_status = (change.get("new_chat_member") or {}).get("status")
    if chat_id == ctx.bot.group_chat_id and new_status in ("left", "kicked"):
        await db_telegram.set_group(ctx.db, ctx.bot.id, None, None)
        logger.info("Bot removed from the store group", extra={"tenant_id": ctx.store.id})
