"""
Stores' Telegram bots — database layer
======================================
telegram_bots is platform-level (see models/telegram.py): every query filters by
tenant_id or by the bot's Telegram id explicitly.

Connecting a bot is check → configure Telegram → save: if Telegram refuses the
webhook or the menu button, nothing is saved and the owner sees why.
"""

import logging
import re
import secrets

from fastapi import status
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from errors import generate_error
from models.telegram import BotStatus, TelegramBot
from models.tenant import MemberRole, Membership, Tenant
from models.user import User
from services.telegram import TelegramClient, TelegramError
from services.telegram_texts import text
from translations import Msg
from utils.crypto import decrypt, encrypt
from utils.i18n import DEFAULT_LANG, Lang

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{30,60}$")


def bot_token(bot: TelegramBot) -> str:
    return decrypt(bot.token_encrypted)


def webhook_url(bot_user_id: int) -> str:
    return f"{settings.PUBLIC_API_URL.rstrip('/')}/telegram/webhook/{bot_user_id}"


def mini_app_url(slug: str) -> str:
    return settings.MINI_APP_URL_TEMPLATE.format(slug=slug)


def store_lang(tenant: Tenant) -> Lang:
    """The store's first language: what its group and its unknown buyers read."""
    first = tenant.languages[0] if tenant.languages else DEFAULT_LANG
    return Lang(first) if first in Lang.__members__ else DEFAULT_LANG


async def get_bot(db: AsyncSession, tenant_id: int) -> TelegramBot | None:
    return await db.scalar(select(TelegramBot).where(TelegramBot.tenant_id == tenant_id))


async def get_bot_by_telegram_id(db: AsyncSession, bot_user_id: int) -> TelegramBot | None:
    return await db.scalar(select(TelegramBot).where(TelegramBot.bot_user_id == bot_user_id))


def get_polling_bots() -> Select[tuple[TelegramBot]]:
    return select(TelegramBot).where(TelegramBot.status == BotStatus.ACTIVE).order_by(TelegramBot.id)


async def configure_telegram(
    client: TelegramClient, token: str, bot_user_id: int, secret: str, tenant: Tenant
) -> None:
    """Webhook (or none, for polling), the Mini App menu button and the commands."""
    if settings.TELEGRAM_MODE == "webhook":
        await client.set_webhook(token, webhook_url(bot_user_id), secret)
    else:
        await client.delete_webhook(token)
    url = mini_app_url(tenant.slug)
    lang = store_lang(tenant)
    if url.startswith("https://"):
        await client.set_menu_button(token, text("menu_button", lang), url)
    for code in Lang:
        await client.set_commands(token, [("start", text("cmd_start", code))], language_code=code.value)


async def connect_bot(
    db: AsyncSession, client: TelegramClient, tenant: Tenant, token: str, lang: Lang = DEFAULT_LANG
) -> TelegramBot:
    token = token.strip()
    if not TOKEN_RE.match(token):
        raise generate_error(Msg.BOT_TOKEN_INVALID, lang, status.HTTP_422_UNPROCESSABLE_CONTENT)
    tenant_id = tenant.id
    try:
        me = await client.get_me(token)
    except TelegramError as exc:
        if exc.code in (401, 404):
            raise generate_error(Msg.BOT_TOKEN_INVALID, lang, status.HTTP_422_UNPROCESSABLE_CONTENT) from None
        raise generate_error(Msg.TELEGRAM_UNAVAILABLE, lang, status.HTTP_503_SERVICE_UNAVAILABLE) from None
    if not me.get("is_bot"):
        raise generate_error(Msg.BOT_TOKEN_INVALID, lang, status.HTTP_422_UNPROCESSABLE_CONTENT)
    bot_user_id = int(me["id"])

    taken = await get_bot_by_telegram_id(db, bot_user_id)
    if taken is not None and taken.tenant_id != tenant_id:
        raise generate_error(Msg.BOT_IN_USE, lang, status.HTTP_409_CONFLICT)

    secret = secrets.token_urlsafe(32)
    try:
        await configure_telegram(client, token, bot_user_id, secret, tenant)
    except TelegramError as exc:
        logger.warning("Bot setup refused by Telegram", extra={"tenant_id": tenant_id, "method": exc.method})
        raise generate_error(
            Msg.BOT_SETUP_FAILED, lang, status.HTTP_502_BAD_GATEWAY, format_values=(exc.description,)
        ) from None

    bot = await get_bot(db, tenant_id)
    old_token = bot_token(bot) if bot is not None and bot.bot_user_id != bot_user_id else None
    if bot is None:
        bot = TelegramBot(tenant_id=tenant_id)
        db.add(bot)
    if old_token is not None:  # a different bot than before: the group must be linked again
        bot.group_chat_id = None
        bot.group_title = None
    bot.bot_user_id = bot_user_id
    bot.username = me.get("username", "")[:64]
    bot.token_encrypted = encrypt(token)
    bot.webhook_secret = secret
    bot.status = BotStatus.ACTIVE
    bot.last_error = None
    bot.polling_offset = None
    await db.commit()
    await db.refresh(bot)
    if old_token is not None:
        await _quiet_delete_webhook(client, old_token)
    logger.info("Bot connected", extra={"tenant_id": tenant_id, "bot_user_id": bot_user_id})
    return bot


async def disconnect_bot(
    db: AsyncSession, client: TelegramClient, tenant_id: int, lang: Lang = DEFAULT_LANG
) -> None:
    bot = await get_bot(db, tenant_id)
    if bot is None:
        raise generate_error(Msg.BOT_NOT_CONNECTED, lang, status.HTTP_404_NOT_FOUND)
    token = bot_token(bot)
    await db.delete(bot)
    await db.commit()
    await _quiet_delete_webhook(client, token)


async def _quiet_delete_webhook(client: TelegramClient, token: str) -> None:
    try:
        await client.delete_webhook(token)
    except TelegramError:
        logger.info("deleteWebhook failed for a replaced bot (ignored)")


# Updates by id, not through a loaded object: the update handlers roll back and
# commit along the way, and an expired ORM object cannot be reloaded lazily in async.
async def set_group(db: AsyncSession, bot_id: int, chat_id: int | None, title: str | None) -> None:
    await db.execute(
        update(TelegramBot)
        .where(TelegramBot.id == bot_id)
        .values(group_chat_id=chat_id, group_title=title[:255] if title else None)
    )
    await db.commit()


async def mark_broken(db: AsyncSession, bot_id: int, reason: str) -> None:
    """Telegram refused the token (revoked in @BotFather): stop using it until reconnected."""
    await db.execute(
        update(TelegramBot)
        .where(TelegramBot.id == bot_id)
        .values(status=BotStatus.BROKEN, last_error=reason[:300])
    )
    await db.commit()
    logger.warning("Bot marked broken", extra={"bot_id": bot_id})


async def save_polling_offset(db: AsyncSession, bot_id: int, offset: int) -> None:
    await db.execute(update(TelegramBot).where(TelegramBot.id == bot_id).values(polling_offset=offset))
    await db.commit()


async def get_member_role_by_telegram(
    db: AsyncSession, tenant_id: int, telegram_user_id: int
) -> MemberRole | None:
    """Is this Telegram user the store's owner or staff? (They signed in with Telegram.)"""
    return await db.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.is_active.is_(True),
            User.telegram_id == telegram_user_id,
            User.is_active.is_(True),
        )
    )
