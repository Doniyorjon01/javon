"""
Users and sessions — database layer
===================================
Platform-level tables (no RLS).

Session tokens: the browser holds a random 256-bit token; the database holds
only its SHA-256. Looking a session up is one indexed query on token_hash.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from errors import generate_error
from models.tenant import Membership, Tenant
from models.user import User, UserSession
from schemas.user import MyStoreOut, UserAdminUpdate
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.plans import access_state

# last_seen_at is refreshed at most this often, so a busy admin panel does not
# turn every read request into a write.
SESSION_TOUCH_INTERVAL = timedelta(minutes=10)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def upsert_telegram_user(
    db: AsyncSession,
    *,
    telegram_id: int,
    first_name: str,
    last_name: str | None = None,
    username: str | None = None,
    lang: Lang = DEFAULT_LANG,
) -> User:
    """
    Create the user on first sign-in, refresh name and username on later ones.
    One atomic statement: two simultaneous first sign-ins cannot create two users.
    """
    stmt = (
        pg_insert(User)
        .values(telegram_id=telegram_id, first_name=first_name, last_name=last_name, username=username)
        .on_conflict_do_update(
            index_elements=[User.telegram_id],
            set_={
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "updated_at": func.now(),
            },
        )
        .returning(User)
    )
    user = (await db.execute(stmt, execution_options={"populate_existing": True})).scalar_one()
    if not user.is_active:
        await db.rollback()
        raise generate_error(Msg.ACCOUNT_DISABLED, lang, status.HTTP_403_FORBIDDEN)
    await db.commit()
    return user


async def create_session(db: AsyncSession, user_id: int, user_agent: str | None) -> str:
    """Returns the raw token for the cookie. It is never stored or logged."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.SESSION_TTL_DAYS),
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    await db.commit()
    return token


async def get_user_by_session(db: AsyncSession, token: str) -> User | None:
    """The signed-in user, or None for an unknown, revoked or expired session or a disabled user."""
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == hash_token(token),
                UserSession.is_active.is_(True),
                UserSession.expires_at > now,
                User.is_active.is_(True),
            )
        )
    ).first()
    if row is None:
        return None
    session, user = row
    if now - session.last_seen_at > SESSION_TOUCH_INTERVAL:
        session.last_seen_at = now
        await db.commit()
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.token_hash == hash_token(token), UserSession.is_active.is_(True))
        .values(is_active=False)
    )
    await db.commit()


async def get_user_stores(db: AsyncSession, user_id: int) -> list[MyStoreOut]:
    rows = await db.execute(
        select(
            Membership.tenant_id,
            Tenant.slug,
            Tenant.name,
            Tenant.status,
            Membership.role,
            Tenant.launched_at,
            Tenant.paused_at,
            Tenant.trial_ends_at,
            Tenant.paid_until,
        )
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == user_id,
            Membership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(Tenant.name, Tenant.id)
    )
    now = datetime.now(UTC)
    return [
        MyStoreOut(
            tenant_id=row.tenant_id,
            slug=row.slug,
            name=row.name,
            status=row.status,
            role=row.role,
            launched_at=row.launched_at,
            paused_at=row.paused_at,
            access=access_state(row.status, row.trial_ends_at, row.paid_until, now),
        )
        for row in rows
    ]


# ------------------------------------------------------------ platform admin


def get_users(telegram_id: int | None = None) -> Select[tuple[User]]:
    """All accounts, newest first; the router paginates."""
    stmt = select(User).order_by(User.id.desc())
    if telegram_id is not None:
        stmt = stmt.where(User.telegram_id == telegram_id)
    return stmt


async def update_user_limits(
    db: AsyncSession, pk: int, data: UserAdminUpdate, lang: Lang = DEFAULT_LANG
) -> User:
    user = await db.get(User, pk)
    if user is None:
        raise generate_error(Msg.USER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user
