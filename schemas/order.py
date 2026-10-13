"""
Order schemas
=============
OrderCreate        the buyer's checkout (public). Prices are NOT sent: the server
                   takes them from the shelf, so a buyer cannot set their own.
OrderTrackOut      what the buyer sees on the tracking page (phone masked).
OrderCreatedOut    OrderTrackOut + tracking_token, returned once at checkout and
                   again on an idempotent retry.
OrderListOut / OrderOut   the store's admin panel.
OrderStatusIn      move an order along (db_order.TRANSITIONS).
"""

from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from models.order import DeliveryType, OrderChannel, OrderStatus, PaymentMethod, PaymentStatus
from schemas.base import BIGINT_MAX, ORMModel
from utils.phone import mask_phone, normalize_phone

MAX_ORDER_LINES = 50
MAX_LINE_QUANTITY = 99


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


BuyerPhone = Annotated[str, AfterValidator(normalize_phone)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=255)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: int = Field(gt=0, le=BIGINT_MAX)
    quantity: int = Field(ge=1, le=MAX_LINE_QUANTITY)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A random UUID the frontend makes once per checkout and resends on retry.
    idempotency_key: UUID
    customer_name: Name
    phone: BuyerPhone
    delivery_type: DeliveryType
    address: Annotated[Address | None, BeforeValidator(_empty_to_none)] = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    comment: Annotated[Comment | None, BeforeValidator(_empty_to_none)] = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    items: list[OrderLineIn] = Field(min_length=1, max_length=MAX_ORDER_LINES)

    @field_validator("items")
    @classmethod
    def _one_line_per_book(cls, items: list[OrderLineIn]) -> list[OrderLineIn]:
        if len({line.book_id for line in items}) != len(items):
            raise ValueError("each book may appear only once; use quantity")
        return items

    @model_validator(mode="after")
    def _delivery_needs_address(self) -> Self:
        if self.delivery_type == DeliveryType.DELIVERY and self.address is None:
            raise ValueError("address is required for delivery")
        if self.delivery_type == DeliveryType.PICKUP:
            # A pickup order has no destination; do not keep one the buyer typed earlier.
            self.address = None
            self.latitude = self.longitude = None
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be sent together")
        return self


class OrderItemOut(ORMModel):
    book_id: int
    title: str
    isbn13: str | None
    unit_price: int
    quantity: int
    line_total: int


class OrderTrackOut(ORMModel):
    id: int
    number: int
    status: OrderStatus
    customer_name: str
    customer_phone: str = Field(exclude=True)
    delivery_type: DeliveryType
    address: str | None
    subtotal: int
    delivery_fee: int
    total: int
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    cancel_reason: str | None
    created_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    items: list[OrderItemOut]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def phone_masked(self) -> str:
        return mask_phone(self.customer_phone)


class OrderCreatedOut(OrderTrackOut):
    # Put it in the tracking link: /buyurtma/{id}?token=... It is shown only here.
    tracking_token: str


class OrderListOut(ORMModel):
    id: int
    number: int
    status: OrderStatus
    channel: OrderChannel
    customer_name: str
    customer_phone: str
    delivery_type: DeliveryType
    total: int
    payment_status: PaymentStatus
    created_at: datetime


class OrderOut(OrderListOut):
    address: str | None
    latitude: float | None
    longitude: float | None
    comment: str | None
    subtotal: int
    delivery_fee: int
    payment_method: PaymentMethod
    cancel_reason: str | None
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    items: list[OrderItemOut]


class OrderStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    reason: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None,
        BeforeValidator(_empty_to_none),
    ] = None  # kept only for cancellation; shown to the buyer


class OrderStatsOut(BaseModel):
    by_status: dict[OrderStatus, int]
