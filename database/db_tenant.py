"""
Tenants (stores) — database layer
=================================
Platform-level table: queries here filter by slug or id explicitly, RLS does
not apply to `tenants` or `memberships` (see models/tenant.py).
"""

from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
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
from utils.slug import slug_candidates, slug_problem, slugify

SLUG_UNIQUE_CONSTRAINT = "uq_tenants_slug"
MAX_SUGGESTIONS = 3

# Statuses whose storefront is visible to buyers.
_PUBLIC_STATUSES = (TenantStatus.TRIAL, TenantStatus.ACTIVE)


async def get_tenant(db: AsyncSession, pk: int, lang: Lang = DEFAULT_LANG) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == pk, Tenant.is_active.is_(True)))
    if tenant is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return tenant


async def get_membership(
    db: AsyncSession, user_id: int, tenant_id: int
) -> tuple[MemberRole, TenantStatus] | None:
    """(role, store status) if the user works in this store, else None.
    Suspended stores are included: their owners still sign in to pay or export data."""
    row = (
        await db.execute(
            select(Membership.role, Tenant.status)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
        )
    ).first()
    return (row.role, row.status) if row else None


async def get_storefront_tenant(db: AsyncSession, slug: str, lang: Lang = DEFAULT_LANG) -> Tenant:
    """The store a buyer is looking at. Stores that are not launched yet, suspended
    or deleted look exactly like missing ones."""
    tenant = await db.scalar(
        select(Tenant).where(
            Tenant.slug == slug,
            Tenant.is_active.is_(True),
            Tenant.status.in_(_PUBLIC_STATUSES),
            Tenant.launched_at.is_not(None),
        )
    )
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
