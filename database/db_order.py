"""
Orders — database layer
=======================
create_order is one transaction that either does everything or nothing:

  1. idempotency: the same idempotency_key returns the first order (a retried
     request after a timeout or a double tap); the same key with a different
     cart is refused (409);
  2. the store's row is locked and its order counter advanced (number 1, 2...);
     this also queues concurrent checkouts of ONE store one after another;
  3. the shelf rows are locked (FOR UPDATE, in id order: no deadlocks), stock
     is checked and decreased — two buyers can never both get the last copy;
  4. customer, order, items (with copied titles, prices, MXIK) and the
     "order created" job (outbox) are written;
  5. commit.

Lock order everywhere that takes both: tenants row, then inventory rows
(db_catalog / db_inventory also lock the tenant row first).

Status changes lock the order row; cancelling puts the stock back on the shelf
in the same transaction.
"""

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import db_job
from database.db_job import JobKind
from database.db_storefront import listed
from database.integrity import constraint_name
from errors import generate_error
from models.catalog import Book
from models.inventory import MAX_QUANTITY, InventoryItem
from models.order import Customer, DeliveryType, Order, OrderItem, OrderStatus, PaymentMethod, PaymentStatus
from models.tenant import Tenant
from schemas.order import OrderCreate
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang

logger = logging.getLogger(__name__)

IDEMPOTENCY_INDEX = "uq_orders_tenant_idempotency_key"
PHONE_SEARCH_MIN_DIGITS = 4  # fewer digits would match almost every phone

TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.ACCEPTED, OrderStatus.CANCELLED}),
    OrderStatus.ACCEPTED: frozenset({OrderStatus.SHIPPING, OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPING: frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def request_hash(data: OrderCreate) -> str:
    """Fingerprint of the cart and details, without the key itself; line order does not matter."""
    canonical = data.model_copy(update={"items": sorted(data.items, key=lambda line: line.book_id)})
    return hashlib.sha256(canonical.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()


def delivery_fee_for(tenant: Tenant, delivery_type: DeliveryType, subtotal: int) -> int:
    if delivery_type == DeliveryType.PICKUP:
        return 0
    if tenant.free_delivery_from is not None and subtotal >= tenant.free_delivery_from:
        return 0
    return tenant.delivery_fee


def _with_items(stmt: Select) -> Select:
    return stmt.options(selectinload(Order.items))


async def _get_by_key(db: AsyncSession, tenant_id: int, key: str) -> Order | None:
    return await db.scalar(
        _with_items(select(Order)).where(Order.tenant_id == tenant_id, Order.idempotency_key == key)
    )


def _replay(order: Order, fingerprint: str, lang: Lang) -> Order:
    if order.request_hash != fingerprint:
        raise generate_error(Msg.IDEMPOTENCY_CONFLICT, lang, status.HTTP_409_CONFLICT)
    return order


async def create_order(
    db: AsyncSession, tenant: Tenant, data: OrderCreate, lang: Lang = DEFAULT_LANG
) -> tuple[Order, bool]:
    """(order, created). created is False for an idempotent replay."""
    tenant_id = tenant.id
    key = str(data.idempotency_key)
    fingerprint = request_hash(data)

    existing = await _get_by_key(db, tenant_id, key)
    if existing is not None:
        return _replay(existing, fingerprint, lang), False

    if data.delivery_type == DeliveryType.DELIVERY and not tenant.delivery_enabled:
        raise generate_error(Msg.DELIVERY_UNAVAILABLE, lang, status.HTTP_409_CONFLICT)
    if data.delivery_type == DeliveryType.PICKUP and not tenant.pickup_enabled:
        raise generate_error(Msg.PICKUP_UNAVAILABLE, lang, status.HTTP_409_CONFLICT)

    # (2) Lock the store's row; the counter gives this order its number.
    number = await db.scalar(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(order_seq=Tenant.order_seq + 1)
        .returning(Tenant.order_seq)
    )

    # (3) Lock the shelf rows being bought.
    wanted = {line.book_id: line.quantity for line in data.items}
    items = list(
        await db.scalars(
            select(InventoryItem)
            .join(Book, Book.id == InventoryItem.book_id)
            .where(listed(tenant_id), InventoryItem.book_id.in_(wanted))
            .order_by(InventoryItem.id)
            .with_for_update(of=InventoryItem)
            .options(selectinload(InventoryItem.book))
        )
    )
    by_book = {item.book_id: item for item in items}
    missing = sorted(set(wanted) - by_book.keys())
    if missing:
        await db.rollback()
        raise generate_error(
            Msg.ORDER_ITEMS_UNAVAILABLE, lang, status.HTTP_409_CONFLICT, extra={"book_ids": missing}
        )
    short = [
        {"book_id": book_id, "available": by_book[book_id].quantity}
        for book_id, quantity in sorted(wanted.items())
        if by_book[book_id].quantity < quantity
    ]
    if short:
        await db.rollback()
        raise generate_error(Msg.OUT_OF_STOCK, lang, status.HTTP_409_CONFLICT, extra={"items": short})

    subtotal = 0
    lines: list[OrderItem] = []
    for line in data.items:
        item = by_book[line.book_id]
        item.quantity -= line.quantity
        line_total = item.price * line.quantity
        subtotal += line_total
        lines.append(
            OrderItem(
                tenant_id=tenant_id,
                book_id=item.book_id,
                title=item.book.title,
                isbn13=item.book.isbn13,
                mxik_code=item.book.mxik_code,
                package_code=item.book.package_code,
                unit_price=item.price,
                quantity=line.quantity,
                line_total=line_total,
            )
        )
    fee = delivery_fee_for(tenant, data.delivery_type, subtotal)

    # (4) Customer (one per phone per store), order, items, outbox job.
    customer_id = await db.scalar(
        pg_insert(Customer)
        .values(tenant_id=tenant_id, phone=data.phone, name=data.customer_name)
        .on_conflict_do_update(
            index_elements=[Customer.tenant_id, Customer.phone],
            set_={"name": data.customer_name, "updated_at": func.now()},
        )
        .returning(Customer.id)
    )
    order = Order(
        tenant_id=tenant_id,
        number=number,
        customer_id=customer_id,
        customer_name=data.customer_name,
        customer_phone=data.phone,
        delivery_type=data.delivery_type,
        address=data.address,
        latitude=data.latitude,
        longitude=data.longitude,
        comment=data.comment,
        subtotal=subtotal,
        delivery_fee=fee,
        total=subtotal + fee,
        payment_method=data.payment_method,
        idempotency_key=key,
        request_hash=fingerprint,
    )
    db.add(order)
    try:
        await db.flush()
        for line in lines:
            line.order_id = order.id
        db.add_all(lines)
        db_job.enqueue(db, JobKind.ORDER_CREATED, tenant_id, {"order_id": order.id})
        await db.commit()  # (5)
    except IntegrityError as exc:
        await db.rollback()
        if constraint_name(exc) == IDEMPOTENCY_INDEX:  # the same checkout, sent twice at once
            existing = await _get_by_key(db, tenant_id, key)
            if existing is not None:
                return _replay(existing, fingerprint, lang), False
        raise
    logger.info("Order created", extra={"tenant_id": tenant_id, "order_id": order.id, "number": number})
    return await get_order(db, tenant_id, order.id, lang), True


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
async def get_order(db: AsyncSession, tenant_id: int, order_id: int, lang: Lang = DEFAULT_LANG) -> Order:
    order = await db.scalar(
        _with_items(select(Order)).where(Order.id == order_id, Order.tenant_id == tenant_id),
        execution_options={"populate_existing": True},
    )
    if order is None:
        raise generate_error(Msg.ORDER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return order


def get_orders(
    tenant_id: int, *, order_status: OrderStatus | None = None, query: str | None = None
) -> Select:
    """
    Newest first. `query`: an order number ("12"), at least 4 digits of the phone
    ("777 00 11"), or part of the name.
    """
    stmt = select(Order).where(Order.tenant_id == tenant_id)
    if order_status is not None:
        stmt = stmt.where(Order.status == order_status)
    if query:
        query = query.strip()
        conditions = [Order.customer_name.icontains(query, autoescape=True)]
        digits = "".join(ch for ch in query if ch.isdigit())
        if digits and len(digits) <= 12:
            conditions.append(Order.number == int(digits))
        if len(digits) >= PHONE_SEARCH_MIN_DIGITS:
            conditions.append(Order.customer_phone.contains(digits, autoescape=True))
        stmt = stmt.where(or_(*conditions))
    return stmt.order_by(Order.created_at.desc(), Order.id.desc())


async def get_stats(db: AsyncSession, tenant_id: int) -> dict[OrderStatus, int]:
    rows = await db.execute(
        select(Order.status, func.count()).where(Order.tenant_id == tenant_id).group_by(Order.status)
    )
    counts = dict.fromkeys(OrderStatus, 0)
    counts.update({row_status: count for row_status, count in rows})
    return counts


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
async def _restock(db: AsyncSession, tenant_id: int, order: Order) -> None:
    """Cancelled: the books go back on the shelf (if the book is still sold here)."""
    for line in order.items:
        await db.execute(
            update(InventoryItem)
            .where(
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.book_id == line.book_id,
                InventoryItem.is_active.is_(True),
            )
            .values(quantity=func.least(InventoryItem.quantity + line.quantity, MAX_QUANTITY))
        )


async def change_status(
    db: AsyncSession,
    tenant_id: int,
    order_id: int,
    new_status: OrderStatus,
    reason: str | None,
    lang: Lang = DEFAULT_LANG,
) -> Order:
    order = await db.scalar(
        _with_items(select(Order))
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .with_for_update(of=Order),
        execution_options={"populate_existing": True},
    )
    if order is None:
        raise generate_error(Msg.ORDER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)

    current = order.status
    allowed = TRANSITIONS[current]
    if order.delivery_type == DeliveryType.PICKUP:
        allowed = allowed - {OrderStatus.SHIPPING}
    if new_status not in allowed:
        await db.rollback()  # expires `order`: use the values read above
        raise generate_error(
            Msg.ORDER_STATUS_INVALID,
            lang,
            status.HTTP_409_CONFLICT,
            format_values=(current.value, new_status.value),
        )

    now = datetime.now(UTC)
    order.status = new_status
    if new_status == OrderStatus.ACCEPTED:
        order.accepted_at = now
    elif new_status == OrderStatus.COMPLETED:
        order.completed_at = now
        if order.payment_method == PaymentMethod.CASH:
            order.payment_status = PaymentStatus.PAID  # cash is paid on handover
    elif new_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        order.cancel_reason = reason
        await _restock(db, tenant_id, order)
    db_job.enqueue(
        db, JobKind.ORDER_STATUS_CHANGED, tenant_id, {"order_id": order.id, "status": new_status.value}
    )
    await db.commit()
    logger.info(
        "Order status changed",
        extra={"tenant_id": tenant_id, "order_id": order.id, "status": new_status.value},
    )
    return await get_order(db, tenant_id, order_id, lang)
