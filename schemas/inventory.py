"""
Inventory schemas
=================
Money is in tiyin (1 so'm = 100 tiyin) everywhere in the API; the frontend shows
so'm. The Excel file is the one exception: people type so'm there, and the
import converts.

InventoryItemCreate   put a catalog book on the store's shelf (owner: sets a price)
InventoryItemUpdate   change price / visibility (owner) or quantity (owner, staff)
StockAdjustIn         "+5 arrived", "-1 damaged": relative, safe next to orders
InventoryItemOut      the row plus the catalog book it points to
InventoryImportOut    an Excel import: status, counters and the error report
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.inventory import MAX_PRICE, MAX_QUANTITY, ImportStatus, QuantityMode
from schemas.base import BIGINT_MAX, ORMModel
from schemas.catalog import BookOut
from translations import Msg
from utils.validation import invalid

Price = int  # tiyin; bounds are set per field below


class InventorySort(StrEnum):
    UPDATED = "updated"  # recently changed first (default)
    TITLE = "title"
    QUANTITY = "quantity"  # fewest first: what to restock


class InventoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: int = Field(gt=0, le=BIGINT_MAX)
    price: Price = Field(gt=0, le=MAX_PRICE)  # a book is never sold for 0
    quantity: int = Field(default=0, ge=0, le=MAX_QUANTITY)
    is_visible: bool = True


class InventoryItemUpdate(BaseModel):
    """Send only what changes. price and is_visible need the owner."""

    model_config = ConfigDict(extra="forbid")

    price: Price | None = Field(default=None, gt=0, le=MAX_PRICE)
    quantity: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    is_visible: bool | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> Self:
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise invalid(Msg.NOT_NULL)
        return self


class StockAdjustIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta: int = Field(ge=-MAX_QUANTITY, le=MAX_QUANTITY)


class InventoryItemOut(ORMModel):
    id: int
    book: BookOut
    price: int
    quantity: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


class InventoryImportOut(ORMModel):
    id: int
    status: ImportStatus
    file_name: str
    quantity_mode: QuantityMode
    total_rows: int
    processed_rows: int
    # {"books_matched", "books_created", "items_added", "items_updated",
    #  "errors": [{"line", "code", "message"}], "errors_truncated": bool}
    report: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
