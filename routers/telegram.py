"""
Telegram: the store's own bot
=============================
The owner (admin panel):
GET    /tenants/{tenant_id}/telegram         the bot, its group, the links to share
PUT    /tenants/{tenant_id}/telegram         {"token": "<from @BotFather>"}: connect or
                                             replace; we set the webhook, the "Store"
                                             menu button (Mini App) and /start
DELETE /tenants/{tenant_id}/telegram         disconnect
POST   /tenants/{tenant_id}/telegram/test    a test message to the linked group

Telegram (not for browsers):
POST   /telegram/webhook/{bot_user_id}       updates for one store's bot; the
                                             X-Telegram-Bot-Api-Secret-Token header
                                             must match that bot's secret

The Mini App (buyers; X-Telegram-Init-Data header):
GET    /storefront/{slug}/telegram/orders    the buyer's orders in this store

Linking the staff group: the owner opens group_link_url, picks the group, and
Telegram adds the bot there with a signed code; the bot links the group only if
the person who added it works in the store (database/db_telegram.py).
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Path, Request, Response, Security, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_owner
from auth.tenant import get_storefront_tenant, require_mini_app_user
from database import db_order, db_telegram, db_tenant
from database.config import bind_tenant, get_pg_db
from errors import generate_error
from models.telegram import TelegramBot
from models.tenant import Tenant
from routers.orders import created_out
from schemas.base import BIGINT_MAX
from schemas.order import OrderCreatedOut
from schemas.telegram import BotConnectIn, BotOut
from services.telegram import TelegramClient, TelegramError
from services.telegram_texts import text
from services.telegram_updates import BotContext, BotInfo, StoreInfo, handle_update
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.redis_cache import get_redis
from utils.signing import group_link_code
from utils.telegram_auth import MiniAppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/{tenant_id}/telegram", tags=["telegram"])
webhook_router = APIRouter(prefix="/telegram", tags=["telegram"], include_in_schema=False)
mini_app_router = APIRouter(prefix="/storefront/{slug}/telegram", tags=["storefront"])

SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105 — a header name
SEEN_TTL_S = 86_400


def get_telegram(request: Request) -> TelegramClient:
    return request.app.state.telegram


def _bot_out(bot: TelegramBot, tenant: Tenant) -> BotOut:
    return BotOut(
        username=bot.username,
        status=bot.status,
        last_error=bot.last_error,
        bot_url=f"https://t.me/{bot.username}",
        group_linked=bot.group_chat_id is not None,
        group_title=bot.group_title,
        group_link_url=f"https://t.me/{bot.username}?startgroup={group_link_code(tenant.id)}",
        mini_app_url=db_telegram.mini_app_url(tenant.slug),
    )


@router.get("", response_model=BotOut)
async def get_bot(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> BotOut:
    bot = await db_telegram.get_bot(db, owner.tenant_id)
    if bot is None:
        raise generate_error(Msg.BOT_NOT_CONNECTED, lang, status.HTTP_404_NOT_FOUND)
    return _bot_out(bot, await db_tenant.get_tenant(db, owner.tenant_id, lang))


@router.put("", response_model=BotOut)
async def connect_bot(
    data: BotConnectIn,
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    client: TelegramClient = Depends(get_telegram),
    lang: Lang = Depends(get_lang),
) -> BotOut:
    tenant = await db_tenant.get_tenant(db, owner.tenant_id, lang)
    bot = await db_telegram.connect_bot(db, client, tenant, data.token, lang)
    return _bot_out(bot, await db_tenant.get_tenant(db, owner.tenant_id, lang))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_bot(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    client: TelegramClient = Depends(get_telegram),
    lang: Lang = Depends(get_lang),
) -> None:
    await db_telegram.disconnect_bot(db, client, owner.tenant_id, lang)


@router.post("/test", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_message(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    client: TelegramClient = Depends(get_telegram),
    lang: Lang = Depends(get_lang),
) -> None:
    bot = await db_telegram.get_bot(db, owner.tenant_id)
    if bot is None or bot.group_chat_id is None:
        raise generate_error(Msg.BOT_GROUP_NOT_LINKED, lang, status.HTTP_409_CONFLICT)
    try:
        await client.send_message(db_telegram.bot_token(bot), bot.group_chat_id, text("test_message", lang))
    except TelegramError as exc:
        raise generate_error(
            Msg.BOT_SETUP_FAILED, lang, status.HTTP_502_BAD_GATEWAY, format_values=(exc.description,)
        ) from None


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
async def _first_time(redis: Redis, bot_id: int, update_id: int) -> bool:
    """Telegram may deliver an update twice (it retries on timeouts): handle it once."""
    try:
        return bool(await redis.set(f"tg:seen:{bot_id}:{update_id}", 1, nx=True, ex=SEEN_TTL_S))
    except RedisError:
        logger.warning("Update de-duplication unavailable; handling anyway")
        return True


@webhook_router.post("/webhook/{bot_user_id}")
async def telegram_webhook(
    request: Request,
    bot_user_id: int = Path(gt=0, le=BIGINT_MAX),
    db: AsyncSession = Depends(get_pg_db),
    redis: Redis = Depends(get_redis),
    client: TelegramClient = Depends(get_telegram),
) -> Response:
    bot = await db_telegram.get_bot_by_telegram_id(db, bot_user_id)
    secret = request.headers.get(SECRET_HEADER, "")
    if bot is None or not hmac.compare_digest(secret, bot.webhook_secret):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        update = await request.json()
        update_id = int(update["update_id"])
    except (ValueError, KeyError, TypeError):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if await _first_time(redis, bot.id, update_id):
        bot_info, tenant_id = BotInfo.of(bot), bot.tenant_id
        await bind_tenant(db, tenant_id)
        tenant = await db_tenant.get_tenant(db, tenant_id)
        ctx = BotContext(
            db=db,
            client=client,
            private_storage=getattr(request.app.state, "private_storage", None),
            bot=bot_info,
            store=StoreInfo.of(tenant),
        )
        try:
            await handle_update(ctx, update)
        except Exception:
            # Answer 200 anyway: a retried update would fail the same way.
            logger.exception("Telegram update failed", extra={"tenant_id": tenant_id, "update_id": update_id})
    return Response(status_code=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# Mini App
# --------------------------------------------------------------------------- #
@mini_app_router.get("/orders", response_model=list[OrderCreatedOut])
async def get_my_orders(
    tenant: Tenant = Depends(get_storefront_tenant),
    user: MiniAppUser = Depends(require_mini_app_user),
    db: AsyncSession = Depends(get_pg_db),
) -> list[OrderCreatedOut]:
    """The last 20 orders of this Telegram user in this store, with their tracking tokens."""
    orders = list(await db.scalars(db_order.get_telegram_buyer_orders(tenant.id, user.id)))
    return [await created_out(db, tenant, order) for order in orders]
