"""
Subscription schemas
====================
PlanOut                 a plan as the pricing page and the owner see it
SubscriptionOut         the owner's view: state, dates, usage, how to pay
SubscriptionPaymentIn   the platform admin records a payment
SubscriptionUpdate      the platform admin corrects plan or dates by hand
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.tenant import Plan, TenantStatus
from schemas.base import ORMModel
from utils.plans import PLANS, YEAR_MONTHS, AccessState, PlanInfo, price

MAX_AMOUNT = 10**12  # tiyin: 10 billion so'm, far above any real payment


class PlanOut(BaseModel):
    plan: Plan
    monthly_price: int  # tiyin
    yearly_price: int  # tiyin, 12 months for the price of 10
    item_limit: int | None  # None = unlimited
    staff_limit: int
    excel_import: bool

    @classmethod
    def of(cls, info: PlanInfo) -> "PlanOut":
        return cls(
            plan=info.plan,
            monthly_price=info.monthly_price,
            yearly_price=price(info.plan, YEAR_MONTHS),
            item_limit=info.item_limit,
            staff_limit=info.staff_limit,
            excel_import=info.excel_import,
        )


def all_plans() -> list[PlanOut]:
    return [PlanOut.of(info) for info in PLANS.values()]


class PlansOut(BaseModel):
    trial_days: int
    plans: list[PlanOut]


class PlatformPaymentOut(BaseModel):
    """Where the owner sends the money. None fields: not configured yet."""

    card_number: str | None
    card_holder: str | None
    support_telegram: str | None


class SubscriptionPaymentOut(ORMModel):
    id: int
    plan: Plan
    months: int
    amount: int
    period_start: datetime
    period_end: datetime
    note: str | None
    is_active: bool  # False: voided by the platform
    created_at: datetime


class SubscriptionOut(BaseModel):
    plan: Plan
    status: TenantStatus
    state: AccessState
    trial_ends_at: datetime | None
    paid_until: datetime | None
    access_until: datetime | None  # the later of the two
    closes_at: datetime | None  # access_until + grace days: storefront hidden after this
    suspended_reason: str | None
    items_used: int
    item_limit: int | None
    staff_used: int
    staff_limit: int
    plans: list[PlanOut]
    pay_to: PlatformPaymentOut
    payments: list[SubscriptionPaymentOut]  # newest first, the last 24


class SubscriptionPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan
    months: int = Field(ge=1, le=36)
    # What actually arrived, in tiyin. Omitted: the list price (utils.plans.price).
    amount: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    note: str | None = Field(default=None, max_length=300)


class SubscriptionUpdate(BaseModel):
    """Manual corrections (a goodwill week, a plan change between payments)."""

    model_config = ConfigDict(extra="forbid")

    plan: Plan | None = None
    trial_ends_at: datetime | None = None
    paid_until: datetime | None = None


class SuspendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=300)
