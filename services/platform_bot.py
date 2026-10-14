"""
The platform bot (javon.uz's own bot)
=====================================
The same bot as the Telegram Login Widget (TELEGRAM_LOGIN_BOT_TOKEN). It talks
to store OWNERS, never to buyers:

    /start          greeting + a "send my phone number" button (request_contact)
    contact         the owner's own number -> users.phone (registration step
                    "Telegram orqali kirish va telefon raqami"); a contact that is
                    not the sender's own is refused
    anything else   a link to the admin panel

and the worker sends owners subscription reminders, payment confirmations and
suspension notices through it (workers/subscriptions.py). Telegram lets a bot
write to a user who signed in with the Login Widget (write access) or pressed
/start; others answer 403, which is logged and skipped.

Updates arrive at POST /telegram/platform (webhook, secret header) or through
scripts/telegram_poll.py locally. The session is NOT bound to a store: users
is a platform table.
"""

import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.user import User
from services.telegram import TelegramClient, TelegramError
from services.telegram_texts import pick_lang, text
from utils.i18n import Lang
from utils.phone import normalize_phone

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/platform"
ALLOWED_UPDATES = ["message"]


def platform_token() -> str | None:
    token = settings.TELEGRAM_LOGIN_BOT_TOKEN
    return token.get_secret_value() if token else None


def webhook_secret() -> str:
    """Derived from SECRET_KEY, so there is nothing extra to configure."""
    key = settings.SECRET_KEY.get_secret_value().encode()
    return hmac.new(key, b"platform-bot-webhook", hashlib.sha256).hexdigest()[:48]


def phone_keyboard(lang: Lang) -> dict[str, Any]:
    return {
        "keyboard": [[{"text": text("platform_phone_button", lang), "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


async def _user_lang(db: AsyncSession, telegram_id: int, sender: dict[str, Any]) -> Lang:
    language = await db.scalar(select(User.language).where(User.telegram_id == telegram_id))
    if language in Lang.__members__:
        return Lang(language)
    return pick_lang(sender.get("language_code"), Lang.uz)


async def handle_platform_update(db: AsyncSession, client: TelegramClient, tg_update: dict[str, Any]) -> None:
    token = platform_token()
    message = tg_update.get("message") or {}
    chat, sender = message.get("chat") or {}, message.get("from") or {}
    if token is None or chat.get("type") != "private" or not sender.get("id"):
        return
    chat_id, telegram_id = int(chat["id"]), int(sender["id"])
    lang = await _user_lang(db, telegram_id, sender)

    async def reply(body: str, markup: dict[str, Any] | None = None) -> None:
        try:
            await client.send_message(token, chat_id, body, markup)
        except TelegramError as exc:
            logger.info("Platform bot could not reply", extra={"method": exc.method, "code": exc.code})

    contact = message.get("contact")
    if contact:
        if int(contact.get("user_id") or 0) != telegram_id:
            await reply(text("platform_phone_not_own", lang), phone_keyboard(lang))
            return
        try:
            phone = normalize_phone(str(contact.get("phone_number", "")))
        except ValueError:
            await reply(text("platform_phone_not_own", lang), phone_keyboard(lang))
            return
        user_id = await db.scalar(
            update(User)
            .where(User.telegram_id == telegram_id, User.is_active.is_(True))
            .values(phone=phone)
            .returning(User.id)
        )
        await db.commit()
        if user_id is None:
            await reply(text("platform_no_account", lang), {"remove_keyboard": True})
            return
        logger.info("Owner phone saved", extra={"user_id": user_id})
        await reply(text("platform_phone_saved", lang, phone=phone), {"remove_keyboard": True})
        return

    if str(message.get("text", "")).split("@")[0].startswith("/start"):
        await reply(text("platform_start", lang), phone_keyboard(lang))
        return
    await reply(text("platform_help", lang, url=settings.APP_URL))
