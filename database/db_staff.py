"""
Staff — database layer
======================
The owner invites with a one-time link; whoever opens it signed in becomes
staff. Rules, all checked with the store's row locked (lock order as
everywhere: tenants first, then the invite), so parallel accepts cannot pass
the plan's staff limit or use one link twice:

  * a link works once, for INVITE_TTL_DAYS, and the owner can revoke it;
  * at most MAX_OPEN_INVITES open links per store;
  * a closed store (suspended or unpaid) takes no new staff;
  * the owner cannot be removed and cannot leave (ownership transfer is a
    separate, explicit operation, later).

Removing someone deactivates their membership: from the next request they get
404 for the store, and its Telegram group buttons stop working for them.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.db_subscription import count_staff
from errors import generate_error
from models.staff import StaffInvite
from models.tenant import MemberRole, Membership, Tenant
from models.user import User
from schemas.staff import InviteCreatedOut, InvitePreviewOut, JoinedStoreOut, MemberOut
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.plans import PLANS, AccessState, access_state

INVITE_TTL_DAYS = 7
MAX_OPEN_INVITES = 10
MAX_TOKEN_LENGTH = 64


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_url(token: str) -> str:
    return f"{settings.APP_URL.rstrip('/')}/taklif/{token}"


def _open(now: datetime) -> tuple:
    return (
        StaffInvite.is_active.is_(True),
        StaffInvite.accepted_at.is_(None),
        StaffInvite.expires_at > now,
    )


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


# --------------------------------------------------------------------------- #
# Invites (owner)
# --------------------------------------------------------------------------- #
async def create_invite(
    db: AsyncSession, tenant_id: int, owner_id: int, lang: Lang = DEFAULT_LANG
) -> InviteCreatedOut:
    tenant = await _lock_tenant(db, tenant_id, lang)
    now = datetime.now(UTC)
    limit = PLANS[tenant.plan].staff_limit
    if await count_staff(db, tenant_id) >= limit:
        await db.rollback()
        raise generate_error(Msg.STAFF_LIMIT_REACHED, lang, status.HTTP_409_CONFLICT, format_values=(limit,))
    open_count = await db.scalar(
        select(func.count()).select_from(StaffInvite).where(StaffInvite.tenant_id == tenant_id, *_open(now))
    )
    if open_count >= MAX_OPEN_INVITES:
        await db.rollback()
        raise generate_error(
            Msg.TOO_MANY_INVITES, lang, status.HTTP_409_CONFLICT, format_values=(MAX_OPEN_INVITES,)
        )
    token = secrets.token_urlsafe(24)
    invite = StaffInvite(
        tenant_id=tenant_id,
        token_hash=_hash(token),
        created_by=owner_id,
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.commit()
    return InviteCreatedOut(id=invite.id, url=invite_url(token), expires_at=invite.expires_at)


async def get_open_invites(db: AsyncSession, tenant_id: int) -> list[StaffInvite]:
    return list(
        await db.scalars(
            select(StaffInvite)
            .where(StaffInvite.tenant_id == tenant_id, *_open(datetime.now(UTC)))
            .order_by(StaffInvite.id.desc())
            .limit(MAX_OPEN_INVITES)
        )
    )


async def revoke_invite(db: AsyncSession, tenant_id: int, invite_id: int, lang: Lang = DEFAULT_LANG) -> None:
    invite = await db.scalar(
        select(StaffInvite).where(
            StaffInvite.id == invite_id,
            StaffInvite.tenant_id == tenant_id,
            StaffInvite.is_active.is_(True),
            StaffInvite.accepted_at.is_(None),
        )
    )
    if invite is None:
        raise generate_error(Msg.INVITE_INVALID, lang, status.HTTP_404_NOT_FOUND)
    invite.is_active = False
    await db.commit()


# --------------------------------------------------------------------------- #
# Invites (the invited person)
# --------------------------------------------------------------------------- #
async def _find_open(db: AsyncSession, token: str, lang: Lang) -> StaffInvite:
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise generate_error(Msg.INVITE_INVALID, lang, status.HTTP_404_NOT_FOUND)
    invite = await db.scalar(
        select(StaffInvite).where(StaffInvite.token_hash == _hash(token), *_open(datetime.now(UTC)))
    )
    if invite is None:
        raise generate_error(Msg.INVITE_INVALID, lang, status.HTTP_404_NOT_FOUND)
    return invite


async def preview_invite(db: AsyncSession, token: str, lang: Lang = DEFAULT_LANG) -> InvitePreviewOut:
    invite = await _find_open(db, token, lang)
    tenant = await db.scalar(select(Tenant).where(Tenant.id == invite.tenant_id, Tenant.is_active.is_(True)))
    if tenant is None:
        raise generate_error(Msg.INVITE_INVALID, lang, status.HTTP_404_NOT_FOUND)
    return InvitePreviewOut(store_name=tenant.name, store_slug=tenant.slug, expires_at=invite.expires_at)


async def accept_invite(
    db: AsyncSession, token: str, user_id: int, lang: Lang = DEFAULT_LANG
) -> JoinedStoreOut:
    tenant_id = (await _find_open(db, token, lang)).tenant_id
    await db.rollback()
    tenant = await _lock_tenant(db, tenant_id, lang)
    invite = await db.scalar(
        select(StaffInvite)
        .where(StaffInvite.token_hash == _hash(token), *_open(datetime.now(UTC)))
        .with_for_update()
    )
    if invite is None:  # used or revoked a moment ago
        await db.rollback()
        raise generate_error(Msg.INVITE_INVALID, lang, status.HTTP_404_NOT_FOUND)

    state = access_state(tenant.status, tenant.trial_ends_at, tenant.paid_until, datetime.now(UTC))
    if state in (AccessState.EXPIRED, AccessState.SUSPENDED):
        await db.rollback()
        msg = Msg.STORE_SUSPENDED if state == AccessState.SUSPENDED else Msg.SUBSCRIPTION_EXPIRED
        raise generate_error(msg, lang, status.HTTP_403_FORBIDDEN)
    already = await db.scalar(
        select(Membership.id).where(
            Membership.user_id == user_id, Membership.tenant_id == tenant_id, Membership.is_active.is_(True)
        )
    )
    if already is not None:
        await db.rollback()
        raise generate_error(Msg.ALREADY_MEMBER, lang, status.HTTP_409_CONFLICT)
    limit = PLANS[tenant.plan].staff_limit
    if await count_staff(db, tenant_id) >= limit:
        await db.rollback()
        raise generate_error(Msg.STAFF_LIMIT_REACHED, lang, status.HTTP_409_CONFLICT, format_values=(limit,))

    db.add(Membership(user_id=user_id, tenant_id=tenant_id, role=MemberRole.STAFF))
    invite.accepted_by, invite.accepted_at = user_id, datetime.now(UTC)
    joined = JoinedStoreOut(tenant_id=tenant_id, slug=tenant.slug, name=tenant.name, role=MemberRole.STAFF)
    try:
        await db.commit()
    except IntegrityError:  # pragma: no cover — the tenant lock serialises accepts
        await db.rollback()
        raise generate_error(Msg.ALREADY_MEMBER, lang, status.HTTP_409_CONFLICT) from None
    return joined


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #
async def get_members(db: AsyncSession, tenant_id: int) -> list[MemberOut]:
    """Owner first, then staff by join date. Bounded by the plan's staff limit."""
    rows = await db.execute(
        select(
            User.id,
            User.first_name,
            User.last_name,
            User.username,
            User.phone,
            Membership.role,
            Membership.created_at,
        )
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id, Membership.is_active.is_(True))
        .order_by((Membership.role == MemberRole.OWNER).desc(), Membership.created_at, Membership.id)
        .limit(max(info.staff_limit for info in PLANS.values()) + 1)
    )
    return [
        MemberOut(
            user_id=row.id,
            first_name=row.first_name,
            last_name=row.last_name,
            username=row.username,
            phone=row.phone,
            role=row.role,
            joined_at=row.created_at,
        )
        for row in rows
    ]


async def remove_member(db: AsyncSession, tenant_id: int, user_id: int, lang: Lang = DEFAULT_LANG) -> None:
    await _lock_tenant(db, tenant_id, lang)
    membership = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.user_id == user_id, Membership.is_active.is_(True)
        )
    )
    if membership is None:
        await db.rollback()
        raise generate_error(Msg.MEMBER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    if membership.role == MemberRole.OWNER:
        await db.rollback()
        raise generate_error(Msg.OWNER_CANNOT_LEAVE, lang, status.HTTP_409_CONFLICT)
    membership.is_active = False
    await db.commit()
