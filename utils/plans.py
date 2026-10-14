"""
Plans and the subscription clock
================================
Prices and limits come from the business plan (kitob-platformasi-reja.md):

    Start      190 000 so'm/oy    300 books    1 staff     no Excel import
    Standart   390 000 so'm/oy    3 000 books  5 staff     Excel import
    Pro        690 000 so'm/oy    unlimited    20 staff    Excel import

A year costs 10 months. Prices are in tiyin, like all money. They change rarely
and every change is a business decision, so they live in code, not settings.

The clock: a store may be used until the later of trial_ends_at and paid_until
(its "access_until"); for SUBSCRIPTION_GRACE_DAYS after that it keeps working
with a warning; then it is EXPIRED: the storefront is hidden and the admin panel
is read-only until a payment is recorded. A store the platform SUSPENDED is the
same, whatever the dates. The state is computed, never stored, so it cannot go
stale: one function here, one SQL condition in db_tenant (storefront_open).
"""

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from config import settings
from models.tenant import Plan, TenantStatus

YEAR_MONTHS = 12
YEAR_PRICE_MONTHS = 10  # pay 10 months, get 12


@dataclass(frozen=True, slots=True)
class PlanInfo:
    plan: Plan
    monthly_price: int  # tiyin
    item_limit: int | None  # different books on sale; None = unlimited
    staff_limit: int  # members besides the owner
    excel_import: bool


PLANS: dict[Plan, PlanInfo] = {
    Plan.START: PlanInfo(Plan.START, 19_000_000, 300, 1, excel_import=False),
    Plan.STANDARD: PlanInfo(Plan.STANDARD, 39_000_000, 3_000, 5, excel_import=True),
    Plan.PRO: PlanInfo(Plan.PRO, 69_000_000, None, 20, excel_import=True),
}


def price(plan: Plan, months: int) -> int:
    """What `months` of `plan` cost; whole years get the yearly discount."""
    years, rest = divmod(months, YEAR_MONTHS)
    monthly = PLANS[plan].monthly_price
    return monthly * (years * YEAR_PRICE_MONTHS + rest)


class AccessState(StrEnum):
    TRIAL = "trial"  # free trial running
    ACTIVE = "active"  # paid period running
    GRACE = "grace"  # ended, still working for SUBSCRIPTION_GRACE_DAYS
    EXPIRED = "expired"  # storefront hidden, admin read-only
    SUSPENDED = "suspended"  # stopped by the platform


CLOSED_STATES = frozenset({AccessState.EXPIRED, AccessState.SUSPENDED})


def grace() -> timedelta:
    return timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS)


def access_until(trial_ends_at: datetime | None, paid_until: datetime | None) -> datetime | None:
    """The later of the two; None when neither is set (no clock: never expires)."""
    dates = [d for d in (trial_ends_at, paid_until) if d is not None]
    return max(dates) if dates else None


def access_state(
    status: TenantStatus, trial_ends_at: datetime | None, paid_until: datetime | None, now: datetime
) -> AccessState:
    if status == TenantStatus.SUSPENDED:
        return AccessState.SUSPENDED
    if paid_until is not None and now <= paid_until:
        return AccessState.ACTIVE
    if trial_ends_at is not None and now <= trial_ends_at:
        return AccessState.TRIAL
    until = access_until(trial_ends_at, paid_until)
    if until is None:
        return AccessState.ACTIVE if status == TenantStatus.ACTIVE else AccessState.TRIAL
    if now <= until + grace():
        return AccessState.GRACE
    return AccessState.EXPIRED


def add_months(moment: datetime, months: int) -> datetime:
    """Calendar months; the 31st becomes the month's last day (Jan 31 + 1 = Feb 28/29)."""
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // 12, month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def next_period_start(trial_ends_at: datetime | None, paid_until: datetime | None, now: datetime) -> datetime:
    """
    Where a new payment's period begins. Paying before the end (or during the
    grace days) continues the current period, so early payers lose nothing and
    the grace days are not free. A store that was already closed starts today.
    """
    until = access_until(trial_ends_at, paid_until)
    if until is not None and now <= until + grace():
        return until
    return now
