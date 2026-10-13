"""
Customers and orders
====================
customers    a buyer of ONE store, identified by phone within that store. Buyers
             have no account: they leave a name and a phone with the order.
orders       numbered 1, 2, 3... inside each store (tenants.order_seq).
order_items  what was bought, with the title, price and fiscal codes COPIED at
             the moment of the order: later catalog or price changes must not
             rewrite an order that was already placed.

All three belong to a store: tenant_id + Row Level Security (migration 0006).
order_items carries tenant_id too, so RLS protects it without a join.

Money in tiyin, BIGINT. total = subtotal + delivery_fee, enforced by a CHECK.

Status flow (db_order.TRANSITIONS):
    new -> accepted -> shipping -> completed
      \\        \\           \\
       +--------+-----------+--> cancelled   (stock goes back on the shelf)
Pickup orders skip "shipping".
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import BaseModel
from models.tenant import enum_check, str_enum


class OrderStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"
    SHIPPING = "shipping"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DeliveryType(StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


class PaymentMethod(StrEnum):
    CASH = "cash"  # Click and Payme come with the payments step


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"


class OrderChannel(StrEnum):
    WEB = "web"
    TELEGRAM = "telegram"  # the Mini App, later


class Customer(BaseModel):
    __tablename__ = "customers"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    phone: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(80))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"),
        Index("uq_customers_tenant_phone", "tenant_id", "phone", unique=True),
    )


class Order(BaseModel):
    __tablename__ = "orders"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    number: Mapped[int] = mapped_column(BigInteger)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus), server_default=OrderStatus.NEW.value)
    channel: Mapped[OrderChannel] = mapped_column(
        str_enum(OrderChannel), server_default=OrderChannel.WEB.value
    )

    # Copied from the customer at order time: what the store must call / deliver to.
    customer_name: Mapped[str] = mapped_column(String(80))
    customer_phone: Mapped[str] = mapped_column(String(16))

    delivery_type: Mapped[DeliveryType] = mapped_column(str_enum(DeliveryType))
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    comment: Mapped[str | None] = mapped_column(String(500))

    subtotal: Mapped[int] = mapped_column(BigInteger)
    delivery_fee: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    total: Mapped[int] = mapped_column(BigInteger)
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus), server_default=PaymentStatus.UNPAID.value
    )

    # The client's random key for this checkout: a retried request (bad network,
    # double tap) returns the first order instead of creating a second one.
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))  # same key + different cart = 409

    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.id", lazy="raise"
    )

    __table_args__ = (
        enum_check("status", OrderStatus, "order_status"),
        enum_check("channel", OrderChannel, "order_channel"),
        enum_check("delivery_type", DeliveryType, "order_delivery_type"),
        enum_check("payment_method", PaymentMethod, "order_payment_method"),
        enum_check("payment_status", PaymentStatus, "order_payment_status"),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(r"customer_phone ~ '^\+[1-9][0-9]{6,14}$'", name="customer_phone_e164"),
        CheckConstraint("delivery_type = 'pickup' OR address IS NOT NULL", name="delivery_has_address"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="location_pair"),
        CheckConstraint(
            "subtotal >= 0 AND delivery_fee >= 0 AND total = subtotal + delivery_fee", name="money_adds_up"
        ),
        CheckConstraint("status <> 'cancelled' OR cancelled_at IS NOT NULL", name="cancelled_has_time"),
        Index("uq_orders_tenant_number", "tenant_id", "number", unique=True),
        Index("uq_orders_tenant_idempotency_key", "tenant_id", "idempotency_key", unique=True),
        # The admin list: newest first, optionally by status.
        Index("ix_orders_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_orders_tenant_created", "tenant_id", "created_at"),
    )


class OrderItem(BaseModel):
    __tablename__ = "order_items"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id", ondelete="RESTRICT"), index=True)

    # Snapshot at order time.
    title: Mapped[str] = mapped_column(String(300))
    isbn13: Mapped[str | None] = mapped_column(String(13))
    mxik_code: Mapped[str | None] = mapped_column(String(17))
    package_code: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[int] = mapped_column(BigInteger)

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND line_total = unit_price * quantity", name="line_total_matches"),
        Index("uq_order_items_order_book", "order_id", "book_id", unique=True),
    )
