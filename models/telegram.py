"""
Stores' Telegram bots
=====================
Each store connects its OWN bot (made with @BotFather): buyers talk to the
store, not to javon. One row per store, one store per bot.

Platform-level table, like `tenants` (no RLS): an incoming webhook names the bot
before we know the store, so the lookup cannot be tenant-scoped. Queries filter
by tenant_id or by the webhook's bot id explicitly.

The token is encrypted (utils/crypto.py); the webhook secret is what Telegram
sends back in X-Telegram-Bot-Api-Secret-Token, so nobody else can post updates
in a bot's name. group_chat_id is the store staff's Telegram group, where new
orders and payment receipts arrive.
"""

from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BaseModel
from models.tenant import enum_check, str_enum


class BotStatus(StrEnum):
    ACTIVE = "active"
    BROKEN = "broken"  # Telegram refused the token (revoked in @BotFather): reconnect


class TelegramBot(BaseModel):
    __tablename__ = "telegram_bots"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"), unique=True
    )
    bot_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)  # Telegram's id of the bot
    username: Mapped[str] = mapped_column(String(64))
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    webhook_secret: Mapped[str] = mapped_column(String(64))
    status: Mapped[BotStatus] = mapped_column(str_enum(BotStatus), server_default=BotStatus.ACTIVE.value)
    last_error: Mapped[str | None] = mapped_column(String(300))
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    group_title: Mapped[str | None] = mapped_column(String(255))
    # getUpdates position, used only in polling mode (local development).
    polling_offset: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        enum_check("status", BotStatus, "bot_status"),
        CheckConstraint("char_length(webhook_secret) >= 32", name="webhook_secret_length"),
    )
