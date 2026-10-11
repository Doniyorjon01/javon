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
    text,
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
