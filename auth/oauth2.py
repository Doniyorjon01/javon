"""
Who is calling, and what may they do
====================================
Same idea as hik-backend's oauth2.py — routes declare `Security(get_current_...)` —
but with server-side sessions in an httpOnly cookie instead of JWTs:

  * the browser's JavaScript never sees the token (XSS cannot steal it);
  * sign-out and "block this user" take effect on the very next request;
  * nothing to refresh, nothing to decode.

Dependencies, from widest to narrowest:
    get_current_user      any signed-in person
    get_current_member    works in the store from the path ({tenant_id}); binds the
                          DB session to that store, so RLS applies from here on.
                          A suspended or expired (unpaid) store is read-only:
                          every write answers 403.
    get_current_owner     the store's owner (prices, settings, payments)
    get_current_sysadmin  platform admin (us)

A store the caller does not work in answers 404, not 403: whether store #42
exists is none of their business.

CSRF: cookies are sent automatically, so every state-changing request must carry
an Origin header from settings.CORS_ORIGINS (our own frontend). Browsers always
send Origin on POST/PUT/PATCH/DELETE and scripts on other sites cannot forge it.
"""

from dataclasses import dataclass

from fastapi import Depends, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_tenant, db_user
from database.config import bind_tenant, get_pg_db
from errors import generate_error
from models.tenant import MemberRole
from models.user import User
from schemas.base import BIGINT_MAX
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.plans import AccessState

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_trusted_origin(request: Request, lang: Lang) -> None:
    if request.method in SAFE_METHODS:
        return
    if request.headers.get("origin") not in settings.CORS_ORIGINS:
        raise generate_error(Msg.ORIGIN_NOT_ALLOWED, lang, status.HTTP_403_FORBIDDEN)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_TTL_DAYS * 86_400,
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> User:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise generate_error(Msg.INVALID_CREDENTIALS, lang, status.HTTP_401_UNAUTHORIZED)
    require_trusted_origin(request, lang)
    user = await db_user.get_user_by_session(db, token)
    if user is None:
        raise generate_error(Msg.INVALID_CREDENTIALS, lang, status.HTTP_401_UNAUTHORIZED)
    return user


@dataclass(frozen=True, slots=True)
class CurrentMember:
    user: User
    tenant_id: int
    role: MemberRole
    access: AccessState


async def get_current_member(
    request: Request,
    tenant_id: int = Path(gt=0, le=BIGINT_MAX),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> CurrentMember:
    membership = await db_tenant.get_membership(db, user.id, tenant_id)
    if membership is None:
        raise generate_error(Msg.STORE_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    # Owners of a suspended or unpaid store still sign in to see their data and pay;
    # nobody changes anything until the platform reactivates it or a payment arrives.
    if membership.read_only and request.method not in SAFE_METHODS:
        msg = Msg.STORE_SUSPENDED if membership.state == AccessState.SUSPENDED else Msg.SUBSCRIPTION_EXPIRED
        raise generate_error(msg, lang, status.HTTP_403_FORBIDDEN)
    await bind_tenant(db, tenant_id)
    return CurrentMember(user=user, tenant_id=tenant_id, role=membership.role, access=membership.state)


async def get_current_owner(
    member: CurrentMember = Depends(get_current_member),
    lang: Lang = Depends(get_lang),
) -> CurrentMember:
    if member.role != MemberRole.OWNER:
        raise generate_error(Msg.FORBIDDEN, lang, status.HTTP_403_FORBIDDEN)
    return member


async def get_current_sysadmin(
    user: User = Depends(get_current_user),
    lang: Lang = Depends(get_lang),
) -> User:
    if not user.is_platform_admin:
        raise generate_error(Msg.FORBIDDEN, lang, status.HTTP_403_FORBIDDEN)
    return user
