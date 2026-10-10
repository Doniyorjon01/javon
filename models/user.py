"""
Users
=====
A person who signs in to the platform (store owner or staff). Platform-level:
no tenant_id, no RLS. One user can belong to several stores via memberships.

Buyers are NOT users: they are per-store `customers` (added with orders).
"""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, String, false
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

    # lazy="raise": async code must load relations explicitly (selectinload).
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", lazy="raise")

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"),
        CheckConstraint("language IN ('uz', 'ru', 'en')", name="language_supported"),
    )