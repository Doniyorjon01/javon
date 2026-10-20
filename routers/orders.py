"""
Orders
======
Buyers (public, no sign-in):
POST /storefront/{slug}/orders                   checkout. 201 with tracking_token; the same
                                                 idempotency_key again -> 200, same order.
                                                 409 out_of_stock / order_items_unavailable
                                                 carry which books; 429 when one IP sends
                                                 too many orders to one store. Inside the
                                                 store's Telegram Mini App the request carries
                                                 X-Telegram-Init-Data: the order is linked to
                                                 that Telegram chat. card_transfer orders get
                                                 the card to pay to in the answer.
GET  /storefront/{slug}/orders/{order_id}?token=  the tracking page
POST /storefront/{slug}/orders/statuses           {"orders": [{"id", "token"}, ...]} (up to 50):
                                                 the status of each order the browser
                                                 remembers ("My orders"); an id with a
                                                 wrong token is simply left out
POST /storefront/{slug}/orders/{order_id}/payment-proof?token=
                                                 multipart "file": the bank app's receipt for
                                                 a card transfer (kept in the PRIVATE bucket)

The store (owner and staff — plan: "xodim buyurtma bilan ishlaydi"):
GET  /tenants/{tenant_id}/orders?status=&q=      newest first; q = number, phone or name
GET  /tenants/{tenant_id}/orders/stats           how many in each status (the badges)
GET  /tenants/{tenant_id}/orders/{order_id}
POST /tenants/{tenant_id}/orders/{order_id}/status   {"status": "accepted"} etc.;
                                                 cancelling returns the books to the shelf;
                                                 a card transfer must be paid before
                                                 shipping / completing (409 order_not_paid)
GET  /tenants/{tenant_id}/orders/{order_id}/payment-proof   the receipt picture
POST /tenants/{tenant_id}/orders/{order_id}/payment  {"approve": true} or
                                                 {"approve": false, "note": "..."}

The checkout is a cookie-less public endpoint, so it needs no CSRF Origin
check; spam is limited per IP instead (ORDER_RATE_LIMIT per ORDER_RATE_WINDOW_S).
"""

from fastapi import APIRouter, Depends, File, Path, Query, Request, Response, Security, UploadFile, status
from fastapi_pagination.ext.sqlalchemy import apaginate
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member
from auth.tenant import get_mini_app_user, get_storefront_tenant
from config import settings
from database import db_order, db_telegram
from database.config import get_pg_db
from errors import generate_error
from models.order import Order, OrderStatus, PaymentMethod
from models.tenant import Tenant
from schemas.base import BIGINT_MAX
from schemas.order import (
    CardTransferOut,
    OrderCreate,
    OrderCreatedOut,
    OrderListOut,
    OrderOut,
    OrderStatsOut,
    OrderStatusesIn,
    OrderStatusIn,
    OrderStatusOut,
    OrderTrackOut,
    PaymentReviewIn,
)
from services.media import delete_image, read_upload, save_image
from services.storage import Storage, get_private_storage
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.images import RECEIPT_SPEC, variant_key
from utils.pagination import CustomPage
from utils.rate_limit import PROOF_LIMIT, hit
from utils.redis_cache import get_redis
from utils.signing import check_order_token, order_start_code, order_token
from utils.telegram_auth import MiniAppUser

public_router = APIRouter(prefix="/storefront/{slug}/orders", tags=["storefront"])
router = APIRouter(prefix="/tenants/{tenant_id}/orders", tags=["orders"])

OrderId = Path(gt=0, le=BIGINT_MAX)


async def created_out(db: AsyncSession, tenant: Tenant, order: Order) -> OrderCreatedOut:
    """The checkout answer: order, tracking token, card to pay to, Telegram link."""
    tracked = OrderTrackOut.model_validate(order)
    card_transfer = None
    if order.payment_method == PaymentMethod.CARD_TRANSFER and tenant.card_number and tenant.card_holder:
        card_transfer = CardTransferOut(
            card_number=tenant.card_number,
            card_holder=tenant.card_holder,
            amount=order.total,
            hold_hours=settings.CARD_TRANSFER_HOLD_HOURS,
        )
    bot = await db_telegram.get_bot(db, tenant.id)
    telegram_link = (
        f"https://t.me/{bot.username}?start={order_start_code(tenant.id, order.id)}"
        if bot is not None
        else None
    )
    return OrderCreatedOut.model_validate(
        {
            **tracked.__dict__,
            "tracking_token": order_token(tenant.id, order.id),
            "card_transfer": card_transfer,
            "telegram_link": telegram_link,
        }
    )


@public_router.post("", response_model=OrderCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    request: Request,
    response: Response,
    tenant: Tenant = Depends(get_storefront_tenant),
    telegram_user: MiniAppUser | None = Depends(get_mini_app_user),
    db: AsyncSession = Depends(get_pg_db),
    redis: Redis = Depends(get_redis),
    lang: Lang = Depends(get_lang),
) -> OrderCreatedOut:
    tenant_id = tenant.id  # read now: a rolled-back transaction expires the ORM object
    client_ip = request.client.host if request.client else "unknown"
    allowed = await hit(
        redis,
        f"order:{tenant_id}:{client_ip}",
        limit=settings.ORDER_RATE_LIMIT,
        window_s=settings.ORDER_RATE_WINDOW_S,
    )
    if not allowed:
        raise generate_error(
            Msg.TOO_MANY_REQUESTS,
            lang,
            status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(settings.ORDER_RATE_WINDOW_S)},
        )
    order, created = await db_order.create_order(db, tenant, data, lang, telegram_user=telegram_user)
    if not created:
        response.status_code = status.HTTP_200_OK
    await db.refresh(tenant)
    return await created_out(db, tenant, order)


def _check_token(tenant_id: int, order_id: int, token: str, lang: Lang) -> None:
    # A wrong token looks exactly like a missing order.
    if not check_order_token(tenant_id, order_id, token):
        raise generate_error(Msg.ORDER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)


@public_router.post("/statuses", response_model=list[OrderStatusOut])
async def order_statuses(
    data: OrderStatusesIn,
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
) -> list[Order]:
    ids = [ref.id for ref in data.orders if check_order_token(tenant.id, ref.id, ref.token)]
    return await db_order.get_statuses(db, tenant.id, ids)


@public_router.post(
    "/{order_id}/payment-proof", response_model=OrderTrackOut, dependencies=[Depends(PROOF_LIMIT)]
)
async def upload_payment_proof(
    file: UploadFile = File(description="Screenshot of the bank app's receipt"),
    order_id: int = OrderId,
    token: str = Query(min_length=10, max_length=64),
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_private_storage),
    lang: Lang = Depends(get_lang),
) -> Order:
    tenant_id = tenant.id
    _check_token(tenant_id, order_id, token, lang)
    order = await db_order.get_order(db, tenant_id, order_id, lang)
    if order.payment_method != PaymentMethod.CARD_TRANSFER:
        raise generate_error(Msg.PAYMENT_PROOF_NOT_EXPECTED, lang, status.HTTP_409_CONFLICT)
    data = await read_upload(file, settings.MAX_UPLOAD_BYTES, lang)
    await db.rollback()  # no transaction open during the conversion and upload
    key = await save_image(storage, f"receipts/{tenant_id}/{order_id}", data, RECEIPT_SPEC, lang)
    try:
        order, replaced = await db_order.attach_payment_proof(db, tenant_id, order_id, key, lang)
    except Exception:
        await delete_image(storage, key, RECEIPT_SPEC)
        raise
    await delete_image(storage, replaced, RECEIPT_SPEC)
    return order


@public_router.get("/{order_id}", response_model=OrderTrackOut)
async def track_order(
    order_id: int = OrderId,
    token: str = Query(min_length=10, max_length=64),
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Order:
    _check_token(tenant.id, order_id, token, lang)
    return await db_order.get_order(db, tenant.id, order_id, lang)


@router.get("", response_model=CustomPage[OrderListOut])
async def get_orders(
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=80, description="Order number, phone or name"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_order.get_orders(member.tenant_id, order_status=order_status, query=q))


@router.get("/stats", response_model=OrderStatsOut)
async def get_stats(
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
) -> OrderStatsOut:
    return OrderStatsOut(by_status=await db_order.get_stats(db, member.tenant_id))


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int = OrderId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Order:
    return await db_order.get_order(db, member.tenant_id, order_id, lang)


@router.post("/{order_id}/status", response_model=OrderOut)
async def change_status(
    data: OrderStatusIn,
    order_id: int = OrderId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Order:
    return await db_order.change_status(db, member.tenant_id, order_id, data.status, data.reason, lang)


@router.get("/{order_id}/payment-proof")
async def get_payment_proof(
    order_id: int = OrderId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_private_storage),
    lang: Lang = Depends(get_lang),
) -> Response:
    """The receipt picture, streamed through the API: the private bucket has no public URL."""
    order = await db_order.get_order(db, member.tenant_id, order_id, lang)
    data = await storage.get(variant_key(order.payment_proof_key, "l")) if order.payment_proof_key else None
    if data is None:
        raise generate_error(Msg.PAYMENT_PROOF_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return Response(content=data, media_type="image/webp", headers={"Cache-Control": "private, no-store"})


@router.post("/{order_id}/payment", response_model=OrderOut)
async def review_payment(
    data: PaymentReviewIn,
    order_id: int = OrderId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Order:
    return await db_order.review_payment(db, member.tenant_id, order_id, data.approve, data.note, lang)
