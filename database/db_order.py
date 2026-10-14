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

Card transfer: the buyer pays to the store's card and sends the bank app's
receipt (website or the store's bot): unpaid -> under_review. The store's staff
confirm (paid) or refuse with a reason (back to unpaid, the buyer may send
another). Such an order cannot be shipped or completed before it is paid, and
the worker cancels it if no receipt arrives within CARD_TRANSFER_HOLD_HOURS.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import db_job
from database.db_job import JobKind
from database.db_storefront import listed
from database.integrity import constraint_name
from errors import generate_error
from models.catalog import Book
from models.inventory import MAX_QUANTITY, InventoryItem
from models.order import (
    Customer,
    DeliveryType,
    Order,
    OrderChannel,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from models.tenant import Tenant
from schemas.order import OrderCreate
from translations import Msg, translate
from utils.i18n import DEFAULT_LANG, Lang
from utils.telegram_auth import MiniAppUser

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
    db: AsyncSession,
    tenant: Tenant,
    data: OrderCreate,
    lang: Lang = DEFAULT_LANG,
    *,
    telegram_user: MiniAppUser | None = None,
) -> tuple[Order, bool]:
    """
    (order, created). created is False for an idempotent replay. `telegram_user`
    is the buyer inside the store's Mini App: the order is marked as coming from
    Telegram and its updates go to that chat.
    """
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
    payment_allowed = {
        PaymentMethod.CASH: tenant.cash_enabled,
        PaymentMethod.CARD_TRANSFER: tenant.card_transfer_enabled,
    }
    if not payment_allowed[data.payment_method]:
        raise generate_error(Msg.PAYMENT_METHOD_UNAVAILABLE, lang, status.HTTP_409_CONFLICT)

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
    customer_values: dict[str, object] = {"name": data.customer_name, "updated_at": func.now()}
    if telegram_user is not None:
        customer_values["telegram_id"] = telegram_user.id
    customer_id = await db.scalar(
        pg_insert(Customer)
        .values(
            tenant_id=tenant_id,
            phone=data.phone,
            name=data.customer_name,
            telegram_id=telegram_user.id if telegram_user else None,
        )
        .on_conflict_do_update(index_elements=[Customer.tenant_id, Customer.phone], set_=customer_values)
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
        channel=OrderChannel.TELEGRAM if telegram_user else OrderChannel.WEB,
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


def _apply_status(db: AsyncSession, order: Order, new_status: OrderStatus, reason: str | None) -> None:
    now = datetime.now(UTC)
    order.status = new_status
    if new_status == OrderStatus.ACCEPTED:
        order.accepted_at = now
    elif new_status == OrderStatus.COMPLETED:
        order.completed_at = now
        if order.payment_method == PaymentMethod.CASH:
            order.payment_status = PaymentStatus.PAID  # cash is paid on handover
            order.paid_at = now
    elif new_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        order.cancel_reason = reason
    _enqueue_for(db, order, JobKind.ORDER_STATUS_CHANGED, {"status": new_status.value})


def _enqueue_for(
    db: AsyncSession, order: Order, kind: JobKind, extra: dict[str, object] | None = None
) -> None:
    db_job.enqueue(db, kind, order.tenant_id, {"order_id": order.id, **(extra or {})})


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
    unpaid_card = (
        order.payment_method == PaymentMethod.CARD_TRANSFER and order.payment_status != PaymentStatus.PAID
    )
    if unpaid_card and new_status in (OrderStatus.SHIPPING, OrderStatus.COMPLETED):
        await db.rollback()
        raise generate_error(Msg.ORDER_NOT_PAID, lang, status.HTTP_409_CONFLICT)

    _apply_status(db, order, new_status, reason)
    if new_status == OrderStatus.CANCELLED:
        await _restock(db, tenant_id, order)
    await db.commit()
    logger.info(
        "Order status changed",
        extra={"tenant_id": tenant_id, "order_id": order.id, "status": new_status.value},
    )
    return await get_order(db, tenant_id, order_id, lang)


# --------------------------------------------------------------------------- #
# Card transfer: receipts and their review
# --------------------------------------------------------------------------- #
PROOF_ACCEPTED_FROM = (PaymentStatus.UNPAID, PaymentStatus.UNDER_REVIEW)
OPEN_STATUSES = (OrderStatus.NEW, OrderStatus.ACCEPTED)


async def _lock_order(db: AsyncSession, tenant_id: int, order_id: int, lang: Lang) -> Order:
    order = await db.scalar(
        _with_items(select(Order))
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .with_for_update(of=Order),
        execution_options={"populate_existing": True},
    )
    if order is None:
        raise generate_error(Msg.ORDER_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return order


async def attach_payment_proof(
    db: AsyncSession,
    tenant_id: int,
    order_id: int,
    proof_key: str,
    lang: Lang = DEFAULT_LANG,
    *,
    telegram_message: tuple[int, int] | None = None,
) -> tuple[Order, str | None]:
    """
    Record the buyer's receipt: -> under_review, and tell the store. Returns the
    order and the key of the receipt it replaces (the caller deletes that file).
    `telegram_message` is (chat_id, message_id) when the buyer sent it to the bot:
    the store's group then gets the picture itself.
    """
    order = await _lock_order(db, tenant_id, order_id, lang)
    acceptable = (
        order.payment_method == PaymentMethod.CARD_TRANSFER
        and order.payment_status in PROOF_ACCEPTED_FROM
        and order.status in OPEN_STATUSES
    )
    if not acceptable:
        await db.rollback()
        raise generate_error(Msg.PAYMENT_PROOF_NOT_EXPECTED, lang, status.HTTP_409_CONFLICT)
    replaced = order.payment_proof_key
    order.payment_proof_key = proof_key
    order.payment_status = PaymentStatus.UNDER_REVIEW
    order.payment_note = None
    extra: dict[str, object] = {}
    if telegram_message is not None:
        extra = {"chat_id": telegram_message[0], "message_id": telegram_message[1]}
    _enqueue_for(db, order, JobKind.PAYMENT_PROOF_RECEIVED, extra)
    await db.commit()
    logger.info("Payment proof received", extra={"tenant_id": tenant_id, "order_id": order_id})
    return await get_order(db, tenant_id, order_id, lang), replaced


async def review_payment(
    db: AsyncSession,
    tenant_id: int,
    order_id: int,
    approve: bool,
    note: str | None,
    lang: Lang = DEFAULT_LANG,
) -> Order:
    """The store's staff checked the receipt: paid, or back to unpaid with the reason."""
    order = await _lock_order(db, tenant_id, order_id, lang)
    if order.payment_status != PaymentStatus.UNDER_REVIEW or order.status not in OPEN_STATUSES:
        await db.rollback()
        raise generate_error(Msg.PAYMENT_NOT_UNDER_REVIEW, lang, status.HTTP_409_CONFLICT)
    if approve:
        order.payment_status = PaymentStatus.PAID
        order.paid_at = datetime.now(UTC)
        order.payment_note = None
    else:
        order.payment_status = PaymentStatus.UNPAID
        order.payment_note = note
    _enqueue_for(db, order, JobKind.PAYMENT_REVIEWED, {"approved": approve})
    await db.commit()
    logger.info("Payment reviewed", extra={"tenant_id": tenant_id, "order_id": order_id, "approved": approve})
    return await get_order(db, tenant_id, order_id, lang)


async def cancel_unpaid_card_orders(db: AsyncSession, tenant_id: int, lang: Lang = DEFAULT_LANG) -> int:
    """
    Card-transfer orders with no receipt for CARD_TRANSFER_HOLD_HOURS: cancel and
    put the books back. A receipt under review is never cancelled automatically.
    The hold counts from the order's last change (updated_at), so a buyer whose
    receipt was refused gets the full hold again to send a new one.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=settings.CARD_TRANSFER_HOLD_HOURS)
    ids = list(
        await db.scalars(
            select(Order.id).where(
                Order.tenant_id == tenant_id,
                Order.payment_method == PaymentMethod.CARD_TRANSFER,
                Order.payment_status == PaymentStatus.UNPAID,
                Order.status.in_(OPEN_STATUSES),
                Order.updated_at < cutoff,
            )
        )
    )
    await db.rollback()
    reason = translate(Msg.ORDER_NOT_PAID_IN_TIME, lang)
    cancelled = 0
    for order_id in ids:
        order = await _lock_order(db, tenant_id, order_id, lang)
        still_unpaid = order.payment_status == PaymentStatus.UNPAID and order.status in OPEN_STATUSES
        if not still_unpaid:  # paid or reviewed meanwhile
            await db.rollback()
            continue
        _apply_status(db, order, OrderStatus.CANCELLED, reason)
        await _restock(db, tenant_id, order)
        await db.commit()
        cancelled += 1
    if cancelled:
        logger.info("Unpaid card orders cancelled", extra={"tenant_id": tenant_id, "count": cancelled})
    return cancelled


# --------------------------------------------------------------------------- #
# Telegram buyers
# --------------------------------------------------------------------------- #
async def link_telegram_buyer(
    db: AsyncSession, tenant_id: int, order_id: int, telegram_user_id: int, lang: Lang = DEFAULT_LANG
) -> Order:
    """The web buyer opened t.me/<bot>?start=o<id>_<token>: updates now go to their chat."""
    order = await get_order(db, tenant_id, order_id, lang)
    await db.execute(
        update(Customer)
        .where(Customer.id == order.customer_id, Customer.tenant_id == tenant_id)
        .values(telegram_id=telegram_user_id)
    )
    await db.commit()
    return order


async def get_buyer_telegram_id(db: AsyncSession, tenant_id: int, order: Order) -> int | None:
    return await db.scalar(
        select(Customer.telegram_id).where(Customer.id == order.customer_id, Customer.tenant_id == tenant_id)
    )


def get_telegram_buyer_orders(tenant_id: int, telegram_user_id: int, limit: int = 20) -> Select:
    """The Mini App's "my orders": orders of every customer row with this Telegram id."""
    return (
        _with_items(select(Order))
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.tenant_id == tenant_id, Customer.telegram_id == telegram_user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )


async def find_order_awaiting_proof(db: AsyncSession, tenant_id: int, telegram_user_id: int) -> Order | None:
    """A receipt photo sent to the bot belongs to this buyer's latest unpaid card order."""
    return await db.scalar(
        select(Order)
        .join(Customer, Customer.id == Order.customer_id)
        .where(
            Order.tenant_id == tenant_id,
            Customer.telegram_id == telegram_user_id,
            Order.payment_method == PaymentMethod.CARD_TRANSFER,
            Order.payment_status.in_(PROOF_ACCEPTED_FROM),
            Order.status.in_(OPEN_STATUSES),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(1)
    )
