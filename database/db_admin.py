"""
Platform admin — database layer
===============================
Cross-store views for the platform admin. Order numbers of all stores come
from the SQL function platform_order_totals() (migration 0008): it runs as the
schema owner, so RLS does not hide other stores, and returns aggregates only.
Everything else here reads platform tables (tenants, memberships, users,
subscription_payments, jobs, books), which have no RLS.

A single store's details (its shelf, staff) are read with the session bound to
that store, like any store request.
"""

from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from database.config import bind_tenant
from database.db_subscription import count_staff
from database.db_tenant import subscription_open
from errors import generate_error
from models.catalog import Book, BookStatus
from models.inventory import InventoryItem
from models.job import Job, JobStatus
from models.subscription import SubscriptionPayment
from models.telegram import TelegramBot
from models.tenant import MemberRole, Membership, Tenant, TenantStatus
from models.user import User
from schemas.admin import JobAdminOut, OwnerOut, TenantAdminDetailOut, TenantAdminOut
from schemas.stats import PlatformMetricsOut
from schemas.subscription import SubscriptionPaymentOut
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.plans import AccessState, access_state
from utils.translit import search_key

RECENT_DAYS = 30


def _order_totals(since: datetime):
    return (
        func.platform_order_totals(since)
        .table_valued("tenant_id", "orders", "sales", "last_order_at")
        .render_derived(name="totals")
    )


def _tenants_query(since: datetime) -> Select:
    owner_membership = aliased(Membership)
    owner = aliased(User)
    totals = _order_totals(since)
    return (
        select(
            Tenant,
            owner.id.label("owner_id"),
            owner.telegram_id.label("owner_telegram_id"),
            owner.first_name.label("owner_first_name"),
            owner.username.label("owner_username"),
            owner.phone.label("owner_phone"),
            func.coalesce(totals.c.orders, 0).label("orders_30d"),
            func.coalesce(totals.c.sales, 0).label("sales_30d"),
            totals.c.last_order_at,
        )
        .outerjoin(
            owner_membership,
            (owner_membership.tenant_id == Tenant.id)
            & (owner_membership.role == MemberRole.OWNER)
            & owner_membership.is_active.is_(True),
        )
        .outerjoin(owner, owner.id == owner_membership.user_id)
        .outerjoin(totals, totals.c.tenant_id == Tenant.id)
        .where(Tenant.is_active.is_(True))
    )


def _tenant_out(row: object, now: datetime, cls: type[TenantAdminOut] = TenantAdminOut, **extra: object):
    tenant: Tenant = row.Tenant  # type: ignore[attr-defined]
    owner = None
    if row.owner_id is not None:  # type: ignore[attr-defined]
        owner = OwnerOut(
            user_id=row.owner_id,  # type: ignore[attr-defined]
            telegram_id=row.owner_telegram_id,  # type: ignore[attr-defined]
            first_name=row.owner_first_name,  # type: ignore[attr-defined]
            username=row.owner_username,  # type: ignore[attr-defined]
            phone=row.owner_phone,  # type: ignore[attr-defined]
        )
    return cls(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        status=tenant.status,
        access=access_state(tenant.status, tenant.trial_ends_at, tenant.paid_until, now),
        plan=tenant.plan,
        trial_ends_at=tenant.trial_ends_at,
        paid_until=tenant.paid_until,
        suspended_reason=tenant.suspended_reason,
        launched_at=tenant.launched_at,
        created_at=tenant.created_at,
        owner=owner,
        orders_30d=row.orders_30d,  # type: ignore[attr-defined]
        sales_30d=row.sales_30d,  # type: ignore[attr-defined]
        last_order_at=row.last_order_at,  # type: ignore[attr-defined]
        **extra,
    )


def get_tenants(
    query: str | None = None, tenant_status: TenantStatus | None = None, closed: bool | None = None
) -> tuple[Select, object]:
    """(statement, transformer) for apaginate: newest stores first."""
    now = datetime.now(UTC)
    stmt = _tenants_query(now - timedelta(days=RECENT_DAYS))
    if query:
        needle = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Tenant.slug.like(needle),
                func.lower(Tenant.name).like(needle),
                func.lower(Tenant.name).like(f"%{search_key(query)}%"),
            )
        )
    if tenant_status is not None:
        stmt = stmt.where(Tenant.status == tenant_status)
    if closed is True:
        stmt = stmt.where(or_(Tenant.status == TenantStatus.SUSPENDED, ~subscription_open(now)))
    elif closed is False:
        stmt = stmt.where(Tenant.status != TenantStatus.SUSPENDED, subscription_open(now))
    stmt = stmt.order_by(Tenant.id.desc())

    def transformer(rows: list) -> list[TenantAdminOut]:
        return [_tenant_out(row, now) for row in rows]

    return stmt, transformer


async def get_tenant_detail(
    db: AsyncSession, tenant_id: int, lang: Lang = DEFAULT_LANG
) -> TenantAdminDetailOut:
    now = datetime.now(UTC)
    row = (
        await db.execute(_tenants_query(now - timedelta(days=RECENT_DAYS)).where(Tenant.id == tenant_id))
    ).first()
    if row is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    bot = await db.scalar(select(TelegramBot).where(TelegramBot.tenant_id == tenant_id))
    payments = list(
        await db.scalars(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.tenant_id == tenant_id)
            .order_by(SubscriptionPayment.id.desc())
            .limit(24)
        )
    )
    staff = await count_staff(db, tenant_id)
    await bind_tenant(db, tenant_id)  # the shelf is a store table (RLS)
    items = await db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.tenant_id == tenant_id, InventoryItem.is_active.is_(True))
    )
    return _tenant_out(
        row,
        now,
        TenantAdminDetailOut,
        items=items,
        staff=staff,
        bot_username=bot.username if bot else None,
        bot_group_linked=bool(bot and bot.group_chat_id),
        payments=[SubscriptionPaymentOut.model_validate(p) for p in payments],
    )


async def platform_metrics(db: AsyncSession) -> PlatformMetricsOut:
    """
    The weekly numbers from the business plan. Store states are computed in
    Python from one small query over `tenants` (hundreds of rows, not millions);
    order numbers come aggregated from platform_order_totals().
    """
    now = datetime.now(UTC)
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    stores = (
        await db.execute(
            select(
                Tenant.status, Tenant.trial_ends_at, Tenant.paid_until, Tenant.launched_at, Tenant.created_at
            ).where(Tenant.is_active.is_(True))
        )
    ).all()
    by_access = dict.fromkeys(AccessState, 0)
    for store in stores:
        by_access[access_state(store.status, store.trial_ends_at, store.paid_until, now)] += 1

    t30 = _order_totals(month)
    month_totals = (
        await db.execute(
            select(func.coalesce(func.sum(t30.c.orders), 0), func.coalesce(func.sum(t30.c.sales), 0))
        )
    ).one()
    t7 = _order_totals(week)
    week_totals = (await db.execute(select(func.count(), func.coalesce(func.sum(t7.c.orders), 0)))).one()

    revenue = await db.scalar(
        select(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).where(
            SubscriptionPayment.is_active.is_(True), SubscriptionPayment.created_at >= month
        )
    )
    job_rows = await db.execute(
        select(Job.status, func.count())
        .where(Job.status.in_([JobStatus.FAILED, JobStatus.QUEUED]))
        .group_by(Job.status)
    )
    jobs = {job_status: count for job_status, count in job_rows}
    return PlatformMetricsOut(
        stores=len(stores),
        by_access=by_access,
        launched=sum(1 for s in stores if s.launched_at is not None),
        new_stores_7d=sum(1 for s in stores if s.created_at >= week),
        new_stores_30d=sum(1 for s in stores if s.created_at >= month),
        active_stores_7d=week_totals[0],
        orders_7d=week_totals[1],
        orders_30d=month_totals[0],
        sales_30d=month_totals[1],
        paying_stores=by_access[AccessState.ACTIVE],
        revenue_30d=revenue,
        books_pending=await db.scalar(
            select(func.count()).select_from(Book).where(Book.status == BookStatus.PENDING)
        ),
        jobs_failed=jobs.get(JobStatus.FAILED, 0),
        jobs_queued=jobs.get(JobStatus.QUEUED, 0),
    )


# --------------------------------------------------------------------------- #
# Background jobs
# --------------------------------------------------------------------------- #
def get_jobs(job_status: JobStatus | None, kind: str | None) -> Select[tuple[Job]]:
    stmt = select(Job).order_by(Job.id.desc())
    if job_status is not None:
        stmt = stmt.where(Job.status == job_status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    return stmt


async def retry_job(db: AsyncSession, job_id: int, lang: Lang = DEFAULT_LANG) -> JobAdminOut:
    """A failed job back to the queue with fresh attempts (after fixing its cause)."""
    job = await db.scalar(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.FAILED)
        .values(status=JobStatus.QUEUED, attempts=0, run_after=func.now(), locked_at=None, finished_at=None)
        .returning(Job)
    )
    if job is None:
        await db.rollback()
        raise generate_error(Msg.JOB_NOT_RETRYABLE, lang, status.HTTP_409_CONFLICT)
    await db.commit()
    return JobAdminOut.model_validate(job)
