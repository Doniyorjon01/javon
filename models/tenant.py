"""
Tenants (stores) and memberships
================================
`tenants` is the store itself; `memberships` says who works in it and as what.

Neither table has Row Level Security: the storefront must find a store by slug
before it knows the tenant, and a user must list their stores across tenants.
Tables that BELONG to a store (inventory, orders, customers, ...) carry
tenant_id and get RLS via database/rls.py.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Index,
    String,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import BaseModel
from utils.slug import SLUG_MAX_LENGTH, SLUG_MIN_LENGTH, SLUG_PATTERN

if TYPE_CHECKING:
    from models.user import User


class TenantStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"  # storefront hidden, data kept


class Plan(StrEnum):
    START = "start"
    STANDARD = "standard"
    PRO = "pro"


class MemberRole(StrEnum):
    OWNER = "owner"  # everything, including prices, settings and payments
    STAFF = "staff"  # orders and stock only


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """
    VARCHAR column for a StrEnum (not a native PG enum: adding a value later is a
    plain migration). Its CHECK is declared separately with enum_check(), because
    Enum(create_constraint=True) makes Alembic autogenerate the same CHECK two or
    three times and the migration then fails with "constraint already exists".
    """
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=16,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    """CHECK (column IN (...)) built from the enum, so code and database never disagree."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class Tenant(BaseModel):
    __tablename__ = "tenants"

    # Never released, even after soft delete — so a plain (not partial) UNIQUE.
    slug: Mapped[str] = mapped_column(String(SLUG_MAX_LENGTH), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[TenantStatus] = mapped_column(
        str_enum(TenantStatus), server_default=TenantStatus.TRIAL.value
    )
    plan: Mapped[Plan] = mapped_column(str_enum(Plan), server_default=Plan.STANDARD.value)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL until the owner presses "launch" at the end of the setup wizard; the
    # storefront is public only after that (db_tenant.get_storefront_tenant).
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- look (wizard step "Ko'rinish") ---
    theme: Mapped[str] = mapped_column(String(32), server_default="classic")
    accent_color: Mapped[str] = mapped_column(String(7), server_default="#2B3BD1")
    logo_key: Mapped[str | None] = mapped_column(String(255))  # key in file storage, not a URL

    # --- contacts (wizard step "Ma'lumotlar") ---
    phone: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    # {"mon": {"open": "09:00:00", "close": "20:00:00"}, "sun": null, ...}
    working_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    telegram_username: Mapped[str | None] = mapped_column(String(32))
    instagram_username: Mapped[str | None] = mapped_column(String(30))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(2)), server_default=text("'{uz}'"))

    # --- delivery and payment (wizard step "Yetkazish va to'lov") ---
    # Money in tiyin. Payment is cash only for now: the store's own cash register
    # gives the fiscal receipt. Click and Payme come with the payments step.
    pickup_enabled: Mapped[bool] = mapped_column(server_default=true())
    delivery_enabled: Mapped[bool] = mapped_column(server_default=false())
    delivery_fee: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    free_delivery_from: Mapped[int | None] = mapped_column(BigInteger)  # order subtotal; NULL = never free
    delivery_area: Mapped[str | None] = mapped_column(String(300))  # "Toshkent shahri ichida", free text
    # How buyers may pay: cash on handover and/or a transfer to the store's card
    # (shown to the buyer at checkout; the buyer sends the receipt, staff check it).
    cash_enabled: Mapped[bool] = mapped_column(server_default=true())
    card_transfer_enabled: Mapped[bool] = mapped_column(server_default=false())
    card_number: Mapped[str | None] = mapped_column(String(16))
    card_holder: Mapped[str | None] = mapped_column(String(80))

    # Last order number given out; orders are numbered 1, 2, 3... per store.
    # Internal: changed only by db_order.create_order, never sent to clients.
    order_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="tenant", lazy="raise")

    __table_args__ = (
        enum_check("status", TenantStatus, "tenant_status"),
        enum_check("plan", Plan, "tenant_plan"),
        CheckConstraint(
            f"slug ~ '{SLUG_PATTERN}' AND char_length(slug) BETWEEN {SLUG_MIN_LENGTH} AND {SLUG_MAX_LENGTH}",
            name="slug_format",
        ),
        CheckConstraint("accent_color ~ '^#[0-9A-Fa-f]{6}$'", name="accent_color_hex"),
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="location_pair"),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180", name="location_range"
        ),
        CheckConstraint("cardinality(languages) >= 1", name="languages_not_empty"),
        CheckConstraint("pickup_enabled OR delivery_enabled", name="some_fulfilment"),
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_not_negative"),
        CheckConstraint("free_delivery_from > 0", name="free_delivery_from_positive"),
        CheckConstraint("order_seq >= 0", name="order_seq_not_negative"),
        CheckConstraint("cash_enabled OR card_transfer_enabled", name="some_payment"),
        CheckConstraint(r"card_number ~ '^[0-9]{16}$'", name="card_number_format"),
        CheckConstraint(
            "NOT card_transfer_enabled OR (card_number IS NOT NULL AND card_holder IS NOT NULL)",
            name="card_transfer_has_card",
        ),
    )


class Membership(BaseModel):
    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[MemberRole] = mapped_column(str_enum(MemberRole))

    user: Mapped["User"] = relationship(back_populates="memberships", lazy="raise")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships", lazy="raise")

    __table_args__ = (
        enum_check("role", MemberRole, "member_role"),
        # One active membership per person per store (a removed member can be re-added).
        Index(
            "uq_memberships_user_tenant_active",
            "user_id",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        # Exactly one active owner per store; ownership transfer is an explicit operation.
        Index(
            "uq_memberships_one_owner",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active AND role = 'owner'"),
        ),
    )
