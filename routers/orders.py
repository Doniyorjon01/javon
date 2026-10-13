"""
Orders
======
Buyers (public, no sign-in):
POST /storefront/{slug}/orders                   checkout. 201 with tracking_token; the same
                                                 idempotency_key again -> 200, same order.
                                                 409 out_of_stock / order_items_unavailable
                                                 carry which books; 429 when one IP sends
                                                 too many orders to one store.
GET  /storefront/{slug}/orders/{order_id}?token=  the tracking page

The store (owner and staff — plan: "xodim buyurtma bilan ishlaydi"):
GET  /tenants/{tenant_id}/orders?status=&q=      newest first; q = number, phone or name
GET  /tenants/{tenant_id}/orders/stats           how many in each status (the badges)
GET  /tenants/{tenant_id}/orders/{order_id}
POST /tenants/{tenant_id}/orders/{order_id}/status   {"status": "accepted"} etc.;
                                                 cancelling returns the books to the shelf

The checkout is a cookie-less public endpoint, so it needs no CSRF Origin
check; spam is limited per IP instead (ORDER_RATE_LIMIT per ORDER_RATE_WINDOW_S).
"""

from fastapi import APIRouter, Depends, Path, Query, Request, Response, Security, status
from fastapi_pagination.ext.sqlalchemy import apaginate
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member
from auth.tenant import get_storefront_tenant
from config import settings
from database import db_order
from database.config import get_pg_db
from errors import generate_error
from models.order import Order, OrderStatus
from models.tenant import Tenant
from schemas.base import BIGINT_MAX
from schemas.order import (
    OrderCreate,
    OrderCreatedOut,
    OrderListOut,
    OrderOut,
    OrderStatsOut,
    OrderStatusIn,
    OrderTrackOut,
)
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.pagination import CustomPage
from utils.rate_limit import hit
from utils.redis_cache import get_redis
from utils.signing import check_order_token, order_token

public_router = APIRouter(prefix="/storefront/{slug}/orders", tags=["storefront"])
router = APIRouter(prefix="/tenants/{tenant_id}/orders", tags=["orders"])

OrderId = Path(gt=0, le=BIGINT_MAX)


def _created_out(tenant_id: int, order: Order) -> OrderCreatedOut:
    tracked = OrderTrackOut.model_validate(order)
    return OrderCreatedOut.model_validate(
        {**tracked.__dict__, "tracking_token": order_token(tenant_id, order.id)}
    )


@public_router.post("", response_model=OrderCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    request: Request,
    response: Response,
    tenant: Tenant = Depends(get_storefront_tenant),
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
    order, created = await db_order.create_order(db, tenant, data, lang)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _created_out(tenant_id, order)


@public_router.get("/{order_id}", response_model=OrderTrackOut)
async def track_order(
    order_id: int = OrderId,
    token: str = Query(min_length=10, max_length=64),
    tenant: Tenant = Depends(get_storefront_tenant),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Order:
    # A wrong token looks exactly like a missing order.
    if not check_order_token(tenant.id, order_id, token):
        raise generate_error(Msg.ORDER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
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
