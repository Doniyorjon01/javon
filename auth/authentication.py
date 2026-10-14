"""
Sign-in routes
==============
POST /auth/telegram   the frontend posts the Telegram Login Widget payload as is;
                      on success the session cookie is set and MeOut returned.
                      At most AUTH_RATE_LIMIT attempts per IP per AUTH_RATE_WINDOW_S.
POST /auth/dev-login  ENV=local/test only: sign in as any Telegram id, no widget
                      (the widget only works on a real domain). Not even registered
                      in staging or production.
POST /auth/logout     revoke this browser's session; safe to call twice
GET  /auth/me         the signed-in user and the stores they work in

A new session token is issued on every sign-in, and the previous one from this
browser is revoked (no session fixation).
"""

import logging
import time

from fastapi import APIRouter, Depends, Request, Response, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import (
    clear_session_cookie,
    get_current_user,
    require_trusted_origin,
    set_session_cookie,
)
from config import settings
from database import db_user
from database.config import get_pg_db
from errors import generate_error
from models.user import User
from schemas.user import DevLoginIn, MeOut, TelegramLoginIn, UserOut
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.rate_limit import AUTH_LIMIT
from utils.telegram_auth import TelegramAuthError, verify_login_widget

router = APIRouter(prefix="/auth", tags=["authentication"])
# Included by main.create_app() only when settings.dev_login_enabled (local, test).
dev_router = APIRouter(prefix="/auth", tags=["authentication"])

logger = logging.getLogger(__name__)


async def _me(db: AsyncSession, user: User) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), stores=await db_user.get_user_stores(db, user.id))


async def _start_session(db: AsyncSession, user: User, request: Request, response: Response) -> MeOut:
    old_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if old_token:
        await db_user.revoke_session(db, old_token)
    token = await db_user.create_session(db, user.id, request.headers.get("user-agent"))
    set_session_cookie(response, token)
    logger.info("User signed in", extra={"user_id": user.id})
    return await _me(db, user)


@router.post("/telegram", response_model=MeOut, dependencies=[Depends(AUTH_LIMIT)])
async def login_with_telegram(
    data: TelegramLoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> MeOut:
    require_trusted_origin(request, lang)
    bot_token = settings.TELEGRAM_LOGIN_BOT_TOKEN
    if bot_token is None:
        raise generate_error(Msg.TELEGRAM_LOGIN_UNAVAILABLE, lang, status.HTTP_503_SERVICE_UNAVAILABLE)

    problem = verify_login_widget(
        data.signed_payload(),
        bot_token.get_secret_value(),
        max_age_s=settings.TELEGRAM_AUTH_MAX_AGE_S,
        now=time.time(),
    )
    if problem is not None:
        logger.info("Telegram sign-in refused", extra={"reason": problem.value})
        msg = Msg.TELEGRAM_AUTH_EXPIRED if problem == TelegramAuthError.EXPIRED else Msg.TELEGRAM_AUTH_INVALID
        raise generate_error(msg, lang, status.HTTP_401_UNAUTHORIZED)

    user = await db_user.upsert_telegram_user(
        db,
        telegram_id=data.id,
        first_name=data.first_name,
        last_name=data.last_name,
        username=data.username,
        lang=lang,
    )
    return await _start_session(db, user, request, response)


@dev_router.post("/dev-login", response_model=MeOut, dependencies=[Depends(AUTH_LIMIT)])
async def dev_login(
    data: DevLoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> MeOut:
    require_trusted_origin(request, lang)
    user = await db_user.upsert_telegram_user(
        db, telegram_id=data.telegram_id, first_name=data.first_name, lang=lang
    )
    return await _start_session(db, user, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> None:
    require_trusted_origin(request, lang)
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        await db_user.revoke_session(db, token)
    clear_session_cookie(response)


@router.get("/me", response_model=MeOut)
async def me(
    user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_pg_db),
) -> MeOut:
    return await _me(db, user)
