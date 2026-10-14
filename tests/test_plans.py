"""The subscription clock and plan prices (no database)."""

from datetime import UTC, datetime, timedelta

import pytest

from models.tenant import Plan, TenantStatus
from utils.plans import (
    PLANS,
    AccessState,
    access_state,
    add_months,
    next_period_start,
    price,
)
from workers.subscriptions import notice_key

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.mark.parametrize(
    ("status", "trial_ends_at", "paid_until", "expected"),
    [
        (TenantStatus.TRIAL, NOW + DAY, None, AccessState.TRIAL),
        (TenantStatus.TRIAL, NOW - DAY, None, AccessState.GRACE),
        (TenantStatus.TRIAL, NOW - 3 * DAY + timedelta(minutes=1), None, AccessState.GRACE),
        (TenantStatus.TRIAL, NOW - 3 * DAY - timedelta(minutes=1), None, AccessState.EXPIRED),
        (TenantStatus.ACTIVE, NOW - 30 * DAY, NOW + DAY, AccessState.ACTIVE),
        (TenantStatus.ACTIVE, NOW - 30 * DAY, NOW - 2 * DAY, AccessState.GRACE),
        (TenantStatus.ACTIVE, NOW - 30 * DAY, NOW - 10 * DAY, AccessState.EXPIRED),
        # A suspended store is closed whatever its dates say.
        (TenantStatus.SUSPENDED, NOW + 10 * DAY, NOW + 10 * DAY, AccessState.SUSPENDED),
        # No clock at all (stores made by hand): open.
        (TenantStatus.TRIAL, None, None, AccessState.TRIAL),
        (TenantStatus.ACTIVE, None, None, AccessState.ACTIVE),
        # Paid while the trial still runs: the paid state wins.
        (TenantStatus.ACTIVE, NOW + DAY, NOW + 40 * DAY, AccessState.ACTIVE),
    ],
)
def test_access_state(
    status: TenantStatus, trial_ends_at: datetime | None, paid_until: datetime | None, expected: AccessState
) -> None:
    assert access_state(status, trial_ends_at, paid_until, NOW) == expected


def test_add_months_keeps_the_day_or_takes_the_last_one() -> None:
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2028, 1, 31, tzinfo=UTC), 1) == datetime(2028, 2, 29, tzinfo=UTC)
    assert add_months(datetime(2026, 11, 15, tzinfo=UTC), 3) == datetime(2027, 2, 15, tzinfo=UTC)
    assert add_months(datetime(2026, 10, 14, tzinfo=UTC), 12) == datetime(2027, 10, 14, tzinfo=UTC)


def test_a_new_period_continues_the_current_one() -> None:
    # Paid during the trial: the period starts when the trial ends (no lost days).
    assert next_period_start(NOW + 5 * DAY, None, NOW) == NOW + 5 * DAY
    # Paid during the grace days: they are not free.
    assert next_period_start(NOW - 2 * DAY, None, NOW) == NOW - 2 * DAY
    assert next_period_start(NOW - 40 * DAY, NOW - DAY, NOW) == NOW - DAY
    # Paid after the store closed: from today.
    assert next_period_start(NOW - 30 * DAY, None, NOW) == NOW
    assert next_period_start(None, None, NOW) == NOW


def test_prices() -> None:
    assert PLANS[Plan.STANDARD].monthly_price == 39_000_000  # 390 000 so'm
    assert price(Plan.STANDARD, 1) == 39_000_000
    assert price(Plan.STANDARD, 3) == 117_000_000
    assert price(Plan.STANDARD, 12) == 390_000_000  # a year = 10 months
    assert price(Plan.START, 14) == 19_000_000 * 12
    assert PLANS[Plan.PRO].item_limit is None
    assert not PLANS[Plan.START].excel_import


def test_reminder_keys() -> None:
    until = NOW + 2 * DAY
    assert notice_key(AccessState.TRIAL, until, NOW) == "ends_soon:2026-10-16"
    assert notice_key(AccessState.TRIAL, NOW + 10 * DAY, NOW) is None
    assert notice_key(AccessState.GRACE, NOW - DAY, NOW) == "grace:2026-10-13"
    assert notice_key(AccessState.EXPIRED, NOW - 9 * DAY, NOW) == "closed:2026-10-05"
    assert notice_key(AccessState.SUSPENDED, NOW - 9 * DAY, NOW) is None
    assert notice_key(AccessState.ACTIVE, None, NOW) is None
