"""
Tenant context dependencies
===========================
A route gets "which store is this request for" from a dependency here, never
from its own parameters. The dependency also binds the request's DB session to
that store, so Row Level Security applies to everything the route reads or writes.

Storefront: the store is addressed by slug in the path, /storefront/{slug}/...
The Next.js frontend maps varaq.javon.uz (and later custom domains) to that path,
so the API never has to trust a Host header.

FastAPI caches dependencies per request: the `db` a route receives from
get_pg_db is the same session bound here.
"""

import time

from fastapi import Depends, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_telegram, db_tenant
from database.config import bind_tenant, get_pg_db
from errors import generate_error
from models.tenant import Tenant
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.slug import SLUG_MAX_LENGTH
from utils.telegram_auth import MiniAppUser, TelegramAuthError, verify_init_data


async def get_storefront_tenant(
    slug: str = Path(min_length=1, max_length=SLUG_MAX_LENGTH),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Tenant:
    tenant = await db_tenant.get_storefront_tenant(db, slug.lower(), lang)
    await bind_tenant(db, tenant.id)
    return tenant


# --------------------------------------------------------------------------- #
# Buyers inside the store's Telegram Mini App
# --------------------------------------------------------------------------- #
INIT_DATA_HEADER = "x-telegram-init-data"


async def get_mini_app_user(
    request: Request,
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> MiniAppUser | None:
    """
    The Telegram user who opened the store's Mini App, from the X-Telegram-Init-Data
    header (Telegram.WebApp.initData, signed with the STORE'S bot token). None when
    the header is absent (an ordinary website visitor); 401 when it is present but
    not genuine — never silently treated as anonymous.
    """
    init_data = request.headers.get(INIT_DATA_HEADER)
    if not init_data:
        return None
    tenant_id = tenant.id
    bot = await db_telegram.get_bot(db, tenant_id)
    if bot is None:
        raise generate_error(Msg.TELEGRAM_AUTH_INVALID, lang, status.HTTP_401_UNAUTHORIZED)
    result = verify_init_data(
        init_data, db_telegram.bot_token(bot), settings.TELEGRAM_INIT_DATA_MAX_AGE_S, time.time()
    )
    if isinstance(result, TelegramAuthError):
        msg = Msg.TELEGRAM_AUTH_EXPIRED if result == TelegramAuthError.EXPIRED else Msg.TELEGRAM_AUTH_INVALID
        raise generate_error(msg, lang, status.HTTP_401_UNAUTHORIZED)
    return result


async def require_mini_app_user(
    user: MiniAppUser | None = Depends(get_mini_app_user),
    lang: Lang = Depends(get_lang),
) -> MiniAppUser:
    if user is None:
        raise generate_error(Msg.TELEGRAM_AUTH_INVALID, lang, status.HTTP_401_UNAUTHORIZED)
    return user
