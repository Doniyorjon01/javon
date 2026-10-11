"""
Tenants (stores) — database layer
=================================
Platform-level table: queries here filter by slug or id explicitly, RLS does
not apply to `tenants` or `memberships` (see models/tenant.py).
"""

from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.integrity import constraint_name
from errors import generate_error
from models.tenant import MemberRole, Membership, Plan, Tenant, TenantStatus
from schemas.tenant import SlugCheckOut, TenantCreate, TenantUpdate
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
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


async def get_member_role(db: AsyncSession, user_id: int, tenant_id: int) -> MemberRole | None:
    """The user's role in an existing store, or None if they do not work there.
    Suspended stores are included: their owners still sign in to pay or export data."""
    return await db.scalar(
        select(Membership.role)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
    )


async def get_storefront_tenant(db: AsyncSession, slug: str, lang: Lang = DEFAULT_LANG) -> Tenant:
    """The store a buyer is looking at. Suspended and deleted stores look like missing ones."""
    tenant = await db.scalar(
        select(Tenant).where(
            Tenant.slug == slug,
            Tenant.is_active.is_(True),
            Tenant.status.in_(_PUBLIC_STATUSES),
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
    """New store in trial, plus its owner membership, in one transaction."""
    if slug_problem(data.slug) == "reserved":
        raise generate_error(Msg.SLUG_RESERVED, lang, status.HTTP_409_CONFLICT, format_values=(data.slug,))

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
    await db.commit()
    await db.refresh(tenant)
    return tenant
