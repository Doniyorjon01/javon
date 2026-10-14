"""
Tenants (stores) — database layer
=================================
Platform-level table: queries here filter by slug or id explicitly, RLS does
not apply to `tenants` or `memberships` (see models/tenant.py).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_job
from database.db_job import JobKind
from database.integrity import constraint_name
from errors import generate_error
from models.inventory import InventoryItem
from models.tenant import MemberRole, Membership, Plan, Tenant, TenantStatus
from models.user import User
from schemas.tenant import SlugCheckOut, TenantCreate, TenantUpdate
from services.media import delete_image, save_image
from services.storage import Storage
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.images import LOGO_SPEC
from utils.plans import AccessState, access_state, grace
from utils.slug import slug_candidates, slug_problem, slugify

SLUG_UNIQUE_CONSTRAINT = "uq_tenants_slug"
MAX_SUGGESTIONS = 3

# Statuses whose storefront is visible to buyers (dates permitting).
_PUBLIC_STATUSES = (TenantStatus.TRIAL, TenantStatus.ACTIVE)


def storefront_visible(now: datetime) -> ColumnElement[bool]:
    return and_(
        Tenant.is_active.is_(True),
        Tenant.status.in_(_PUBLIC_STATUSES),
        Tenant.launched_at.is_not(None),
        subscription_open(now),
    )


def subscription_open(now: datetime) -> ColumnElement[bool]:
    """
    SQL twin of utils.plans.access_state() not in CLOSED_STATES, for the dates:
    the later of trial_ends_at / paid_until plus the grace days is still ahead
    (no dates at all = no clock). Keep the two in step.
    """
    until = func.greatest(Tenant.trial_ends_at, Tenant.paid_until)
    return or_(until.is_(None), until > now - grace())


@dataclass(frozen=True, slots=True)
class MemberAccess:
    role: MemberRole
    state: AccessState

    @property
    def read_only(self) -> bool:
        return self.state in (AccessState.EXPIRED, AccessState.SUSPENDED)


async def get_tenant(db: AsyncSession, pk: int, lang: Lang = DEFAULT_LANG) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == pk, Tenant.is_active.is_(True)))
    if tenant is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return tenant


async def get_membership(db: AsyncSession, user_id: int, tenant_id: int) -> MemberAccess | None:
    """The user's role and the store's subscription state, or None if they do not
    work there. Suspended and expired stores are included: their owners still sign
    in to see their data and pay."""
    row = (
        await db.execute(
            select(Membership.role, Tenant.status, Tenant.trial_ends_at, Tenant.paid_until)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
        )
    ).first()
    if row is None:
        return None
    return MemberAccess(
        role=row.role,
        state=access_state(row.status, row.trial_ends_at, row.paid_until, datetime.now(UTC)),
    )


async def get_active_tenant_ids(db: AsyncSession) -> list[int]:
    """For the worker's periodic tasks."""
    return list(await db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)).order_by(Tenant.id)))


async def get_storefront_tenant(db: AsyncSession, slug: str, lang: Lang = DEFAULT_LANG) -> Tenant:
    """The store a buyer is looking at. Stores that are not launched yet, suspended,
    expired (unpaid past the grace days) or deleted look exactly like missing ones."""
    tenant = await db.scalar(select(Tenant).where(Tenant.slug == slug, storefront_visible(datetime.now(UTC))))
    if tenant is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return tenant


async def get_taken_slugs(db: AsyncSession, slugs: list[str]) -> set[str]:
    """Deleted stores included: a slug is never released."""
    if not slugs:
        return set()
    rows = await db.scalars(select(Tenant.slug).where(Tenant.slug.in_(slugs)))
    return set(rows)


async def check_slug(db: AsyncSession, slug: str) -> SlugCheckOut:
    """Is `slug` free? If not, offer up to MAX_SUGGESTIONS free alternatives (one query)."""
    problem = slug_problem(slug)
    base = slugify(slug)  # "Varaq!" -> "varaq": the cleaned form is the best first suggestion
    candidates = [base] if base != slug and slug_problem(base) is None else []
    candidates += slug_candidates(base)
    taken = await get_taken_slugs(db, [slug, *candidates])

    reason = problem or ("taken" if slug in taken else None)
    suggestions = [] if reason is None else [c for c in candidates if c not in taken][:MAX_SUGGESTIONS]
    return SlugCheckOut(slug=slug, available=reason is None, reason=reason, suggestions=suggestions)


async def create_tenant(
    db: AsyncSession, owner_id: int, data: TenantCreate, lang: Lang = DEFAULT_LANG
) -> Tenant:
    """
    New store in trial, plus its owner membership, in one transaction.

    Each account may own at most `users.max_stores` stores (1 by default; the
    platform admin raises it). The user's row is locked first, so two parallel
    requests from one account are counted one after the other and cannot both
    slip under the limit. The trial is per store, so the limit is also what stops
    "a new store every 14 days" trial farming.
    """
    if slug_problem(data.slug) == "reserved":
        raise generate_error(Msg.SLUG_RESERVED, lang, status.HTTP_409_CONFLICT, format_values=(data.slug,))

    max_stores = await db.scalar(
        select(User.max_stores).where(User.id == owner_id).with_for_update(key_share=True)
    )
    owned = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == owner_id,
            Membership.role == MemberRole.OWNER,
            Membership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
    )
    if max_stores is None or owned >= max_stores:
        await db.rollback()
        raise generate_error(
            Msg.STORE_LIMIT_REACHED, lang, status.HTTP_403_FORBIDDEN, format_values=(max_stores or 0,)
        )

    tenant = Tenant(
        name=data.name,
        slug=data.slug,
        status=TenantStatus.TRIAL,
        plan=Plan.STANDARD,
        trial_ends_at=datetime.now(UTC) + timedelta(days=settings.TRIAL_DAYS),
    )
    db.add(tenant)
    try:
        await db.flush()  # assigns tenant.id; fails here if the slug was taken meanwhile
        db.add(Membership(user_id=owner_id, tenant_id=tenant.id, role=MemberRole.OWNER))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if constraint_name(exc) == SLUG_UNIQUE_CONSTRAINT:
            raise generate_error(
                Msg.SLUG_TAKEN, lang, status.HTTP_409_CONFLICT, format_values=(data.slug,)
            ) from exc
        raise
    await db.refresh(tenant)  # server defaults (theme, languages, ...) and timestamps
    return tenant


async def update_tenant(db: AsyncSession, pk: int, data: TenantUpdate, lang: Lang = DEFAULT_LANG) -> Tenant:
    tenant = await get_tenant(db, pk, lang)
    # mode="json": time and enum values become plain strings for the JSONB column.
    for field, value in data.model_dump(exclude_unset=True, mode="json").items():
        setattr(tenant, field, value)
    if (tenant.latitude is None) != (tenant.longitude is None):
        await db.rollback()
        raise generate_error(Msg.LOCATION_INCOMPLETE, lang)
    if not (tenant.pickup_enabled or tenant.delivery_enabled):
        await db.rollback()
        raise generate_error(Msg.FULFILMENT_REQUIRED, lang)
    if not (tenant.cash_enabled or tenant.card_transfer_enabled):
        await db.rollback()
        raise generate_error(Msg.PAYMENT_OPTION_REQUIRED, lang)
    if tenant.card_transfer_enabled and not (tenant.card_number and tenant.card_holder):
        await db.rollback()
        raise generate_error(Msg.CARD_DETAILS_REQUIRED, lang)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def launch_tenant(db: AsyncSession, pk: int, lang: Lang = DEFAULT_LANG) -> Tenant:
    """Make the storefront public. Needs at least one book on sale (an empty shop
    is not worth opening). Calling it again changes nothing (the first launch
    date is kept). A suspended store never reaches here: writes to it are
    refused in get_current_member."""
    tenant = await get_tenant(db, pk, lang)
    if tenant.launched_at is None:
        on_sale = await db.scalar(
            select(InventoryItem.id)
            .where(
                InventoryItem.tenant_id == pk,
                InventoryItem.is_active.is_(True),
                InventoryItem.is_visible.is_(True),
            )
            .limit(1)
        )
        if on_sale is None:
            raise generate_error(Msg.LAUNCH_NEEDS_BOOKS, lang, status.HTTP_409_CONFLICT)
        tenant.launched_at = func.now()
        await db.commit()
        await db.refresh(tenant)
    return tenant


# --------------------------------------------------------------------------- #
# Logo
# --------------------------------------------------------------------------- #
async def set_logo(
    db: AsyncSession, storage: Storage, pk: int, data: bytes, lang: Lang = DEFAULT_LANG
) -> Tenant:
    await get_tenant(db, pk, lang)
    await db.rollback()  # do not hold the transaction open during the upload
    new_key = await save_image(storage, f"logos/{pk}", data, LOGO_SPEC, lang)
    tenant = await db.get(Tenant, pk, with_for_update=True, populate_existing=True)
    if tenant is None:  # pragma: no cover — stores are never deleted
        await delete_image(storage, new_key, LOGO_SPEC)
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    old_key, tenant.logo_key = tenant.logo_key, new_key
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await delete_image(storage, new_key, LOGO_SPEC)
        raise
    await delete_image(storage, old_key, LOGO_SPEC)
    await db.refresh(tenant)
    return tenant


async def delete_logo(db: AsyncSession, storage: Storage, pk: int, lang: Lang = DEFAULT_LANG) -> Tenant:
    tenant = await get_tenant(db, pk, lang)
    old_key, tenant.logo_key = tenant.logo_key, None
    await db.commit()
    await delete_image(storage, old_key, LOGO_SPEC)
    await db.refresh(tenant)
    return tenant


# --------------------------------------------------------------------------- #
# Platform admin: suspend and reactivate
# --------------------------------------------------------------------------- #
async def set_suspended(
    db: AsyncSession, pk: int, reason: str | None, lang: Lang = DEFAULT_LANG, *, notify: bool = False
) -> Tenant:
    """reason given: suspend (storefront hidden, admin read-only); None: reactivate.
    Reactivation returns the store to "active" if it ever paid, else to "trial"
    (its dates decide whether it is actually open). notify: tell the owner in
    Telegram (the job is committed with the change)."""
    tenant = await db.scalar(
        select(Tenant)
        .where(Tenant.id == pk, Tenant.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tenant is None:
        await db.rollback()
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    if reason is not None:
        tenant.status, tenant.suspended_reason = TenantStatus.SUSPENDED, reason
        if notify:
            db_job.enqueue(db, JobKind.OWNER_NOTICE, pk, {"notice": "suspended"})
    else:
        tenant.status = TenantStatus.ACTIVE if tenant.paid_until else TenantStatus.TRIAL
        tenant.suspended_reason = None
    await db.commit()
    await db.refresh(tenant)
    return tenant
