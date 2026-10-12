"""
Users and their sessions
========================
A person who signs in to the platform (store owner or staff). Platform-level:
no tenant_id, no RLS. One user can belong to several stores via memberships.

Buyers are NOT users: they are per-store `customers` (added with orders).
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import BaseModel

if TYPE_CHECKING:
    from models.tenant import Membership


class User(BaseModel):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(2), server_default="uz")
    is_platform_admin: Mapped[bool] = mapped_column(server_default=false(), default=False)
    # How many stores this account may own. The platform admin raises it for a
    # chain of bookshops; see db_tenant.create_tenant.
    max_stores: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))

    # lazy="raise": async code must load relations explicitly (selectinload).
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", lazy="raise")

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"),
        CheckConstraint("language IN ('uz', 'ru', 'en')", name="language_supported"),
        CheckConstraint("max_stores BETWEEN 0 AND 100", name="max_stores_range"),
    )


class UserSession(BaseModel):
    """
    One signed-in browser. The cookie holds a random token; only its SHA-256 is
    stored, so a leaked database dump cannot be replayed as live sessions.
    Sign-out sets is_active = False; expired rows are cleaned up by a job later.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(lazy="raise")
