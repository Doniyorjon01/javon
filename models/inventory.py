"""
Store inventory
===============
inventory_items  one row per book a store sells: the store's price and stock for
                 a book from the shared catalog. A book appears in the store's
                 storefront only through this table.
inventory_imports  one uploaded Excel file and what became of it; processed by
                 the background worker (workers/inventory_import.py).

Both belong to a store: tenant_id + Row Level Security (migration 0005).

Money is in tiyin (1 so'm = 100 tiyin), BIGINT. Stock never goes below zero:
the CHECK holds even if application code is wrong, and orders decrease it with
a conditional UPDATE inside the order's transaction.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import BaseModel
from models.tenant import enum_check, str_enum

if TYPE_CHECKING:
    from models.catalog import Book

MAX_PRICE = 100_000_000_000  # tiyin = 1 billion so'm; anything above is a typo
MAX_QUANTITY = 1_000_000


class InventoryItem(BaseModel):
    __tablename__ = "inventory_items"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id", ondelete="RESTRICT"), index=True)
    price: Mapped[int] = mapped_column(BigInteger)  # tiyin
    quantity: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # False: kept in the admin panel but not shown to buyers.
    is_visible: Mapped[bool] = mapped_column(server_default=true(), default=True)

    book: Mapped["Book"] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint(f"price >= 0 AND price <= {MAX_PRICE}", name="price_range"),
        CheckConstraint(f"quantity >= 0 AND quantity <= {MAX_QUANTITY}", name="quantity_range"),
        # One live row per book per store; a removed book can be added again.
        Index(
            "uq_inventory_items_tenant_book_live",
            "tenant_id",
            "book_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        # The admin list ("recently changed first") and storefront listing.
        Index("ix_inventory_items_tenant_updated", "tenant_id", "updated_at"),
    )


class QuantityMode(StrEnum):
    """What an Excel import does with the "quantity" column of a book already on the shelf."""

    ADD = "add"  # a delivery: "2 arrived" -> stock + 2 (the default)
    SET = "set"  # a stocktake: "there are 2 now" -> stock = 2


class ImportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"  # finished; rows that could not be imported are listed in report
    FAILED = "failed"  # the file itself could not be processed


class InventoryImport(BaseModel):
    __tablename__ = "inventory_imports"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"))
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[ImportStatus] = mapped_column(
        str_enum(ImportStatus), server_default=ImportStatus.QUEUED.value
    )
    file_name: Mapped[str] = mapped_column(String(255))
    # The uploaded .xlsx (at most MAX_UPLOAD_BYTES). Cleared once processed: the
    # report is what the store needs afterwards, not the file.
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    lang: Mapped[str] = mapped_column(String(2), server_default="uz")  # language of the report
    quantity_mode: Mapped[QuantityMode] = mapped_column(
        str_enum(QuantityMode), server_default=QuantityMode.ADD.value
    )
    total_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    processed_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # {"books_matched": n, "books_created": n, "items_added": n, "items_updated": n,
    #  "errors": [{"line": 7, "code": "...", "message": "..."}, ...]}
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        enum_check("status", ImportStatus, "import_status"),
        enum_check("quantity_mode", QuantityMode, "import_quantity_mode"),
        CheckConstraint("processed_rows >= 0 AND total_rows >= 0", name="row_counts"),
        Index("ix_inventory_imports_tenant_created", "tenant_id", "created_at"),
    )
