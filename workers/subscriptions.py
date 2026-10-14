"""
Subscription reminders, owner notices and clean-up
==================================================
Run by workers/main.py.

scan_reminders()  periodic: for every store whose access ends within
                  REMIND_DAYS, has ended (grace days) or has closed, record the
                  notice key in tenants.subscription_notice and queue an
                  owner_notice job, in one transaction. The UPDATE only matches
                  when the key changed, so each reminder goes out once even with
                  several workers. A payment resets the key (db_subscription).

owner_notice()    job handler: one message from the platform bot to the store's
                  owner, in the owner's language. Nothing is sent when the
                  platform bot is not configured; an owner who never allowed the
                  bot to write (403) or blocked it is logged and skipped. Stale
                  reminders (paid meanwhile) are dropped.

cleanup()         hourly: deletes expired sessions, finished jobs and old invites
                  after CLEANUP_AFTER_DAYS. Excel files of finished imports are
                  dropped per store (RLS) in cleanup_store(); their reports stay.
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_job
from database.db_job import JobKind
from models.inventory import ImportStatus, InventoryImport
from models.job import Job, JobStatus
from models.staff import StaffInvite
from models.tenant import MemberRole, Membership, Tenant
from models.user import User, UserSession
from services.platform_bot import platform_token
from services.telegram import TelegramError
from services.telegram_texts import TEXTS, raw, text
from utils.i18n import Lang
from utils.plans import AccessState, access_state, access_until, grace
from workers import notifications

logger = logging.getLogger(__name__)

REMIND_DAYS = 3
TASHKENT = ZoneInfo("Asia/Tashkent")


def notice_key(state: AccessState, until: datetime | None, now: datetime) -> str | None:
    """Which reminder the store is due, as "<kind>:<date the period ends>"."""
    if until is None or state == AccessState.SUSPENDED:
        return None
    day = until.astimezone(TASHKENT).date().isoformat()
    if state in (AccessState.TRIAL, AccessState.ACTIVE) and until - now <= timedelta(days=REMIND_DAYS):
        return f"ends_soon:{day}"
    if state == AccessState.GRACE:
        return f"grace:{day}"
    if state == AccessState.EXPIRED:
        return f"closed:{day}"
    return None


async def scan_reminders(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(
                Tenant.id,
                Tenant.status,
                Tenant.trial_ends_at,
                Tenant.paid_until,
                Tenant.subscription_notice,
            ).where(Tenant.is_active.is_(True))
        )
    ).all()
    queued = 0
    for row in rows:
        state = access_state(row.status, row.trial_ends_at, row.paid_until, now)
        key = notice_key(state, access_until(row.trial_ends_at, row.paid_until), now)
        if key is None or key == row.subscription_notice:
            continue
        claimed = await db.scalar(
            update(Tenant)
            .where(Tenant.id == row.id, Tenant.subscription_notice.is_distinct_from(key))
            .values(subscription_notice=key)
            .returning(Tenant.id)
        )
        if claimed is not None:
            db_job.enqueue(db, JobKind.OWNER_NOTICE, row.id, {"notice": key.split(":")[0]})
            queued += 1
        await db.commit()
    return queued


def _date(moment: datetime) -> str:
    return moment.astimezone(TASHKENT).strftime("%d.%m.%Y")


def _how_to_pay(lang: Lang) -> str:
    card, holder, support = (
        settings.PLATFORM_CARD_NUMBER,
        settings.PLATFORM_CARD_HOLDER,
        settings.PLATFORM_SUPPORT_TELEGRAM,
    )
    if not (card and holder and support):
        return ""
    spaced = " ".join(card[i : i + 4] for i in range(0, len(card), 4))
    return text("sub_how_to_pay", lang, card=spaced, holder=holder, support=support)


def build_notice(notice: str, tenant: Tenant, lang: Lang, now: datetime) -> str | None:
    """The message, or None when it no longer applies (paid or reopened meanwhile)."""
    store = tenant.name
    state = access_state(tenant.status, tenant.trial_ends_at, tenant.paid_until, now)
    until = access_until(tenant.trial_ends_at, tenant.paid_until)
    if notice == "paid":
        if tenant.paid_until is None:
            return None
        plan = TEXTS[f"plan_{tenant.plan.value}"][lang]
        return text("sub_paid", lang, store=store, plan=plan, date=_date(tenant.paid_until))
    if notice == "suspended":
        if state != AccessState.SUSPENDED:
            return None
        return text("store_suspended_notice", lang, store=store, reason=tenant.suspended_reason or "—")
    current = notice_key(state, until, now)
    if until is None or current is None or current.split(":")[0] != notice:
        return None
    if notice == "ends_soon":
        on_trial = state == AccessState.TRIAL
        period = TEXTS["sub_period_trial" if on_trial else "sub_period_paid"][lang]
        body = text("sub_ends_soon", lang, store=store, period=period, date=_date(until))
    elif notice == "grace":
        body = text("sub_grace", lang, store=store, date=_date(until + grace()))
    else:
        body = text("sub_closed", lang, store=store)
    return raw(body + _how_to_pay(lang))


async def owner_notice(db: AsyncSession, job: Job) -> None:
    token = platform_token()
    if token is None or job.tenant_id is None:
        logger.info("Owner notice skipped: no platform bot", extra={"job_id": job.id})
        return
    tenant = await db.get(Tenant, job.tenant_id)
    owner = await db.scalar(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.tenant_id == job.tenant_id,
            Membership.role == MemberRole.OWNER,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if tenant is None or owner is None:
        return
    lang = Lang(owner.language) if owner.language in Lang.__members__ else Lang.uz
    message = build_notice(str(job.payload.get("notice")), tenant, lang, datetime.now(UTC))
    if message is None:
        logger.info("Owner notice no longer applies", extra={"job_id": job.id, "tenant_id": job.tenant_id})
        return
    try:
        await notifications.get_client().send_message(token, owner.telegram_id, message)
    except TelegramError as exc:
        if exc.code in (400, 403):  # never allowed the bot to write, or blocked it
            logger.info("Owner notice not delivered", extra={"tenant_id": job.tenant_id, "code": exc.code})
            return
        raise


async def cleanup(db: AsyncSession) -> dict[str, int]:
    """Platform tables. Returns how many rows each step removed (for the log)."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.CLEANUP_AFTER_DAYS)
    removed = {}
    removed["sessions"] = (
        await db.execute(
            delete(UserSession).where(
                or_(UserSession.expires_at < now, UserSession.is_active.is_(False)),
                UserSession.updated_at < cutoff,
            )
        )
    ).rowcount
    removed["jobs"] = (
        await db.execute(delete(Job).where(Job.status == JobStatus.DONE, Job.finished_at < cutoff))
    ).rowcount
    removed["invites"] = (
        await db.execute(
            delete(StaffInvite).where(
                StaffInvite.accepted_at.is_(None),
                or_(StaffInvite.expires_at < cutoff, StaffInvite.is_active.is_(False)),
                StaffInvite.updated_at < cutoff,
            )
        )
    ).rowcount
    await db.commit()
    return removed


async def cleanup_store(db: AsyncSession, tenant_id: int) -> int:
    """The uploaded Excel files of the store's finished imports (session bound to the store)."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.CLEANUP_AFTER_DAYS)
    result = await db.execute(
        update(InventoryImport)
        .where(
            InventoryImport.tenant_id == tenant_id,
            InventoryImport.status.in_([ImportStatus.DONE, ImportStatus.FAILED]),
            InventoryImport.finished_at < cutoff,
            InventoryImport.file_data.is_not(None),
        )
        .values(file_data=None)
    )
    await db.commit()
    return result.rowcount
