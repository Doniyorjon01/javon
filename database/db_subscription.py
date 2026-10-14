"""
Subscriptions — database layer
===============================
The platform admin records payments by hand; each one extends the store's
paid_until (utils/plans.next_period_start: an early or grace-days payment
continues the current period, a closed store starts today). The store's row is
locked while its dates change, so two payments recorded at once both count.

tenants.paid_until is always the latest period_end of the store's active
payments; voiding a payment recomputes it. A manual PATCH may set it directly
(a goodwill week); the next payment or void recomputes from the payments again.
"""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_job
from database.db_job import JobKind
from errors import generate_error
from models.inventory import InventoryItem
from models.subscription import SubscriptionPayment
from models.tenant import MemberRole, Membership, Tenant, TenantStatus
from schemas.subscription import (
    PlatformPaymentOut,
    SubscriptionOut,
    SubscriptionPaymentIn,
    SubscriptionPaymentOut,
    SubscriptionUpdate,
    all_plans,
)
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.plans import PLANS, access_state, access_until, add_months, grace, next_period_start, price

HISTORY_SIZE = 24


async def _lock_tenant(db: AsyncSession, tenant_id: int, lang: Lang) -> Tenant:
    tenant = await db.scalar(
        select(Tenant)
        .where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tenant is None:
        await db.rollback()
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return tenant


async def count_staff(db: AsyncSession, tenant_id: int) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == MemberRole.STAFF,
            Membership.is_active.is_(True),
        )
    )


async def get_subscription(db: AsyncSession, tenant_id: int, lang: Lang = DEFAULT_LANG) -> SubscriptionOut:
    """The owner's subscription page. The session is bound to the store (inventory count under RLS)."""
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True)))
    if tenant is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    items_used = await db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.tenant_id == tenant_id, InventoryItem.is_active.is_(True))
    )
    payments = list(
        await db.scalars(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.tenant_id == tenant_id)
            .order_by(SubscriptionPayment.id.desc())
            .limit(HISTORY_SIZE)
        )
    )
    until = access_until(tenant.trial_ends_at, tenant.paid_until)
    info = PLANS[tenant.plan]
    return SubscriptionOut(
        plan=tenant.plan,
        status=tenant.status,
        state=access_state(tenant.status, tenant.trial_ends_at, tenant.paid_until, datetime.now(UTC)),
        trial_ends_at=tenant.trial_ends_at,
        paid_until=tenant.paid_until,
        access_until=until,
        closes_at=until + grace() if until else None,
        suspended_reason=tenant.suspended_reason if tenant.status == TenantStatus.SUSPENDED else None,
        items_used=items_used,
        item_limit=info.item_limit,
        staff_used=await count_staff(db, tenant_id),
        staff_limit=info.staff_limit,
        plans=all_plans(),
        pay_to=PlatformPaymentOut(
            card_number=settings.PLATFORM_CARD_NUMBER,
            card_holder=settings.PLATFORM_CARD_HOLDER,
            support_telegram=settings.PLATFORM_SUPPORT_TELEGRAM,
        ),
        payments=[SubscriptionPaymentOut.model_validate(p) for p in payments],
    )


def get_payments(tenant_id: int) -> Select[tuple[SubscriptionPayment]]:
    return (
        select(SubscriptionPayment)
        .where(SubscriptionPayment.tenant_id == tenant_id)
        .order_by(SubscriptionPayment.id.desc())
    )


async def record_payment(
    db: AsyncSession, tenant_id: int, data: SubscriptionPaymentIn, admin_id: int, lang: Lang = DEFAULT_LANG
) -> SubscriptionPayment:
    tenant = await _lock_tenant(db, tenant_id, lang)
    now = datetime.now(UTC)
    start = next_period_start(tenant.trial_ends_at, tenant.paid_until, now)
    payment = SubscriptionPayment(
        tenant_id=tenant_id,
        plan=data.plan,
        months=data.months,
        amount=data.amount if data.amount is not None else price(data.plan, data.months),
        period_start=start,
        period_end=add_months(start, data.months),
        note=data.note,
        recorded_by=admin_id,
    )
    db.add(payment)
    tenant.paid_until = payment.period_end
    tenant.plan = data.plan
    tenant.subscription_notice = None  # reminders start over for the new period
    if tenant.status == TenantStatus.TRIAL:
        tenant.status = TenantStatus.ACTIVE
    db_job.enqueue(db, JobKind.OWNER_NOTICE, tenant_id, {"notice": "paid"})
    await db.commit()
    await db.refresh(payment)
    return payment


async def void_payment(db: AsyncSession, payment_id: int, lang: Lang = DEFAULT_LANG) -> SubscriptionPayment:
    tenant_id = await db.scalar(
        select(SubscriptionPayment.tenant_id).where(SubscriptionPayment.id == payment_id)
    )
    if tenant_id is None:
        raise generate_error(Msg.PAYMENT_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    tenant = await _lock_tenant(db, tenant_id, lang)
    payment = await db.get(SubscriptionPayment, payment_id, populate_existing=True)
    if payment is None or not payment.is_active:
        await db.rollback()
        raise generate_error(Msg.PAYMENT_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    payment.is_active = False
    await db.flush()
    tenant.paid_until = await db.scalar(
        select(func.max(SubscriptionPayment.period_end)).where(
            SubscriptionPayment.tenant_id == tenant_id, SubscriptionPayment.is_active.is_(True)
        )
    )
    if tenant.paid_until is None and tenant.status == TenantStatus.ACTIVE:
        tenant.status = TenantStatus.TRIAL  # never paid after all
    tenant.subscription_notice = None
    await db.commit()
    await db.refresh(payment)
    return payment


async def update_subscription(
    db: AsyncSession, tenant_id: int, data: SubscriptionUpdate, lang: Lang = DEFAULT_LANG
) -> Tenant:
    tenant = await _lock_tenant(db, tenant_id, lang)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "plan" and value is None:
            continue  # the plan column is NOT NULL; "no change"
        setattr(tenant, field, value)
    tenant.subscription_notice = None
    await db.commit()
    await db.refresh(tenant)
    return tenant
