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
from translations import Msg
from utils import validation
from utils.phone import mask_phone
from utils.validation import invalid

MAX_ORDER_LINES = 50
MAX_LINE_QUANTITY = 99


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


BuyerPhone = Annotated[str, AfterValidator(validation.phone)]
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
            raise invalid(Msg.DUPLICATE_ORDER_LINES)
        return items

    @model_validator(mode="after")
    def _delivery_needs_address(self) -> Self:
        if self.delivery_type == DeliveryType.DELIVERY and self.address is None:
            raise invalid(Msg.ADDRESS_REQUIRED)
        if self.delivery_type == DeliveryType.PICKUP:
            # A pickup order has no destination; do not keep one the buyer typed earlier.
            self.address = None
            self.latitude = self.longitude = None
        if (self.latitude is None) != (self.longitude is None):
            raise invalid(Msg.LOCATION_PAIR)
        return self


class OrderItemOut(ORMModel):
    book_id: int
    title: str
    isbn13: str | None
    unit_price: int
    quantity: int
    line_total: int


class CardTransferOut(BaseModel):
    """What the buyer must transfer, and where (shown after a card-transfer checkout)."""

    card_number: str
    card_holder: str
    amount: int  # tiyin
    hold_hours: int  # unpaid orders are cancelled after this


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
    payment_note: str | None  # why the store did not accept the receipt
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
    # Card transfer: where to send the money (then upload the receipt, or send it to the bot).
    card_transfer: CardTransferOut | None = None
    # https://t.me/<store bot>?start=...: status messages in Telegram. None without a bot.
    telegram_link: str | None = None


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
    payment_note: str | None
    paid_at: datetime | None
    payment_proof_key: str | None = Field(default=None, exclude=True)
    cancel_reason: str | None
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    items: list[OrderItemOut]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_payment_proof(self) -> bool:
        """A receipt can be opened at GET .../orders/{id}/payment-proof."""
        return self.payment_proof_key is not None


class OrderStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    reason: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None,
        BeforeValidator(_empty_to_none),
    ] = None  # kept only for cancellation; shown to the buyer


class PaymentReviewIn(BaseModel):
    """The staff's decision on a card-transfer receipt. A refusal needs a reason
    the buyer will read."""

    model_config = ConfigDict(extra="forbid")

    approve: bool
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)] | None = None

    @model_validator(mode="after")
    def _refusal_has_reason(self) -> Self:
        if not self.approve and not self.note:
            raise invalid(Msg.REFUSAL_NOTE_REQUIRED)
        return self


class OrderStatsOut(BaseModel):
    by_status: dict[OrderStatus, int]


class OrderRefIn(BaseModel):
    """An order the buyer's browser remembers, with its tracking token."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0, le=BIGINT_MAX)
    token: str = Field(min_length=10, max_length=64)


class OrderStatusesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[OrderRefIn] = Field(min_length=1, max_length=50)


class OrderStatusOut(ORMModel):
    id: int
    number: int
    status: OrderStatus
    payment_status: PaymentStatus
