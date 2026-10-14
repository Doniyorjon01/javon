"""
Subscription payments
=====================
One row per payment the platform admin records by hand (owners pay by card
transfer; automatic payments come later). A payment buys `months` of `plan` and
covers [period_start, period_end); the store's tenants.paid_until is the latest
period_end of its active payments. A mistaken payment is voided (is_active =
False), never deleted, so the history stays honest.

Platform-level table (no RLS): only the platform admin writes it; the owner
reads their own store's rows through an explicit tenant_id filter.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BaseModel
from models.tenant import Plan, enum_check, str_enum


class SubscriptionPayment(BaseModel):
    __tablename__ = "subscription_payments"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    plan: Mapped[Plan] = mapped_column(str_enum(Plan))
    months: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[int] = mapped_column(BigInteger)  # tiyin, what was actually received
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(300))
    recorded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        enum_check("plan", Plan, "subscription_plan"),
        CheckConstraint("months BETWEEN 1 AND 36", name="months_range"),
        CheckConstraint("amount >= 0", name="amount_not_negative"),
        CheckConstraint("period_end > period_start", name="period_order"),
        Index("ix_subscription_payments_tenant", "tenant_id", "period_end"),
    )
