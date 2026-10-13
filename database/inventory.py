"""
Inventory — database layer
==========================
A store's shelf: price and stock per catalog book. Every function takes
tenant_id and filters by it; RLS (the session is bound to the store) is the
second wall.

Stock changes are relative and conditional where they can race with orders:
`UPDATE ... SET quantity = quantity + :delta WHERE quantity + :delta >= 0`
cannot lose an order's decrement and never goes below zero.

How many different books a store may sell depends on its plan
(PLAN_ITEM_LIMITS, from the business plan). Adding a book locks the store's row
first, so parallel adds cannot pass the limit.
"""

import asyncio

from fastapi import status
from sqlalchemy import Select, and_, false, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import db_catalog, db_job
from database.db_job import JobKind
from database.integrity import constraint_name
from errors import generate_error
from models.catalog import Book
from models.inventory import InventoryImport, InventoryItem
from models.tenant import MemberRole, Plan, Tenant
from schemas.inventory import InventoryItemCreate, InventoryItemUpdate, InventorySort
from services.excel import ExcelError, read_rows
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.isbn import normalize_isbn
from utils.translit import search_key

ITEM_UNIQUE_INDEX = "uq_inventory_items_tenant_book_live"

# Different books on sale per plan; None = unlimited. Trial stores are on STANDARD.
PLAN_ITEM_LIMITS: dict[Plan, int | None] = {Plan.START: 300, Plan.STANDARD: 3000, Plan.PRO: None}


def _with_book(stmt: Select) -> Select:
    return stmt.options(
        selectinload(InventoryItem.book).selectinload(Book.authors),
        selectinload(InventoryItem.book).selectinload(Book.publisher),
    )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def get_items(
    tenant_id: int,
    *,
    query: str | None = None,
    in_stock: bool | None = None,
    visible: bool | None = None,
    sort: InventorySort = InventorySort.UPDATED,
) -> Select:
    """The store's shelf for the admin panel; the router paginates."""
    stmt = (
        select(InventoryItem)
        .join(Book, Book.id == InventoryItem.book_id)
        .where(InventoryItem.tenant_id == tenant_id, InventoryItem.is_active.is_(True))
    )
    if query:
        isbn13 = normalize_isbn(query)
        key = search_key(query)
        conditions = [Book.search_text.contains(key)] if key else []
        if isbn13:
            conditions.append(Book.isbn13 == isbn13)
        stmt = stmt.where(or_(*conditions)) if conditions else stmt.where(false())
    if in_stock is not None:
        stmt = stmt.where(InventoryItem.quantity > 0 if in_stock else InventoryItem.quantity == 0)
    if visible is not None:
        stmt = stmt.where(InventoryItem.is_visible.is_(visible))
    order = {
        InventorySort.UPDATED: (InventoryItem.updated_at.desc(), InventoryItem.id.desc()),
        InventorySort.TITLE: (Book.title, InventoryItem.id),
        InventorySort.QUANTITY: (InventoryItem.quantity, Book.title, InventoryItem.id),
    }[sort]
    return _with_book(stmt).order_by(*order)


async def get_item(
    db: AsyncSession, tenant_id: int, item_id: int, lang: Lang = DEFAULT_LANG
) -> InventoryItem:
    item = await db.scalar(
        _with_book(select(InventoryItem)).where(
            InventoryItem.id == item_id,
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.is_active.is_(True),
        ),
        execution_options={"populate_existing": True},
    )
    if item is None:
        raise generate_error(Msg.INVENTORY_ITEM_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return item


async def get_item_by_isbn(
    db: AsyncSession, tenant_id: int, raw_isbn: str, lang: Lang = DEFAULT_LANG
) -> InventoryItem:
    """Barcode scanner on the shelf: "do we have this one, and how many?"."""
    isbn13 = normalize_isbn(raw_isbn)
    if isbn13 is None:
        raise generate_error(Msg.INVALID_ISBN, lang, format_values=(raw_isbn,))
    item = await db.scalar(
        _with_book(select(InventoryItem))
        .join(Book, Book.id == InventoryItem.book_id)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.is_active.is_(True),
            Book.isbn13 == isbn13,
        )
    )
    if item is None:
        raise generate_error(Msg.INVENTORY_ITEM_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return item


async def _find_item_id(db: AsyncSession, tenant_id: int, book_id: int) -> int | None:
    return await db.scalar(
        select(InventoryItem.id).where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.book_id == book_id,
            InventoryItem.is_active.is_(True),
        )
    )


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
async def _check_item_limit(db: AsyncSession, tenant_id: int, lang: Lang) -> None:
    """Lock the store's row and count its books; raise if the plan is full."""
    plan = await db.scalar(select(Tenant.plan).where(Tenant.id == tenant_id).with_for_update(key_share=True))
    limit = PLAN_ITEM_LIMITS.get(plan) if plan is not None else 0
    if limit is None:
        return
    count = await db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.tenant_id == tenant_id, InventoryItem.is_active.is_(True))
    )
    if count >= limit:
        await db.rollback()
        raise generate_error(Msg.PLAN_ITEM_LIMIT, lang, status.HTTP_403_FORBIDDEN, format_values=(limit,))


async def create_item(
    db: AsyncSession, tenant_id: int, data: InventoryItemCreate, lang: Lang = DEFAULT_LANG
) -> InventoryItem:
    # Only a book this store may see: approved, or its own pending submission.
    await db_catalog.get_book(db, tenant_id, data.book_id, lang)
    existing = await _find_item_id(db, tenant_id, data.book_id)
    if existing is not None:
        raise generate_error(
            Msg.INVENTORY_ITEM_EXISTS, lang, status.HTTP_409_CONFLICT, extra={"item_id": existing}
        )
    await _check_item_limit(db, tenant_id, lang)

    item = InventoryItem(tenant_id=tenant_id, **data.model_dump())
    db.add(item)
    try:
        await db.commit()
    except IntegrityError as exc:  # a parallel request added the same book first
        await db.rollback()
        if constraint_name(exc) == ITEM_UNIQUE_INDEX:
            raise generate_error(
                Msg.INVENTORY_ITEM_EXISTS,
                lang,
                status.HTTP_409_CONFLICT,
                extra={"item_id": await _find_item_id(db, tenant_id, data.book_id)},
            ) from exc
        raise
    return await get_item(db, tenant_id, item.id, lang)


OWNER_FIELDS = frozenset({"price", "is_visible"})


async def update_item(
    db: AsyncSession,
    tenant_id: int,
    item_id: int,
    data: InventoryItemUpdate,
    role: MemberRole,
    lang: Lang = DEFAULT_LANG,
) -> InventoryItem:
    """Staff may correct the stock count; price and visibility are the owner's."""
    changes = data.model_dump(exclude_unset=True)
    if role != MemberRole.OWNER and OWNER_FIELDS & changes.keys():
        raise generate_error(Msg.FORBIDDEN, lang, status.HTTP_403_FORBIDDEN)
    item = await get_item(db, tenant_id, item_id, lang)
    for field, value in changes.items():
        setattr(item, field, value)
    await db.commit()
    return await get_item(db, tenant_id, item_id, lang)


async def adjust_quantity(
    db: AsyncSession, tenant_id: int, item_id: int, delta: int, lang: Lang = DEFAULT_LANG
) -> InventoryItem:
    """Relative change in one statement: safe while orders decrease the same row."""
    result = await db.execute(
        update(InventoryItem)
        .where(
            InventoryItem.id == item_id,
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.is_active.is_(True),
            InventoryItem.quantity + delta >= 0,
            InventoryItem.quantity + delta <= 1_000_000,
        )
        .values(quantity=InventoryItem.quantity + delta)
    )
    if result.rowcount == 0:
        await db.rollback()
        item = await get_item(db, tenant_id, item_id, lang)  # 404 if it does not exist
        raise generate_error(
            Msg.STOCK_OUT_OF_RANGE, lang, status.HTTP_409_CONFLICT, extra={"quantity": item.quantity}
        )
    await db.commit()
    return await get_item(db, tenant_id, item_id, lang)


async def delete_item(db: AsyncSession, tenant_id: int, item_id: int, lang: Lang = DEFAULT_LANG) -> None:
    """Off the shelf (soft delete). Past orders keep their own copy of the book data."""
    item = await get_item(db, tenant_id, item_id, lang)
    item.is_active = False
    await db.commit()


async def upsert_from_import(
    db: AsyncSession, tenant_id: int, book_id: int, price: int, quantity: int, lang: Lang
) -> bool:
    """Excel row: set price and quantity, adding the book if needed. True if added.
    The file says how many there are now, so quantity is SET, not added."""
    item_id = await _find_item_id(db, tenant_id, book_id)
    if item_id is not None:
        await db.execute(
            update(InventoryItem)
            .where(InventoryItem.id == item_id, InventoryItem.tenant_id == tenant_id)
            .values(price=price, quantity=quantity)
        )
        await db.commit()
        return False
    await _check_item_limit(db, tenant_id, lang)
    db.add(InventoryItem(tenant_id=tenant_id, book_id=book_id, price=price, quantity=quantity))
    await db.commit()
    return True


# --------------------------------------------------------------------------- #
# Excel import
# --------------------------------------------------------------------------- #
async def create_import(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    file_name: str,
    data: bytes,
    lang: Lang = DEFAULT_LANG,
) -> InventoryImport:
    """
    Check that the file is a readable sheet with the needed columns (so the store
    hears about a wrong file at once), then queue it for the worker. The import
    row and its job are committed together.
    """
    try:
        rows = await asyncio.to_thread(read_rows, data, settings.MAX_IMPORT_ROWS)
    except ExcelError as exc:
        raise generate_error(
            Msg.IMPORT_FILE_INVALID,
            lang,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            format_values=(settings.MAX_IMPORT_ROWS,),
            extra={"reason": exc.problem.value},
        ) from None

    record = InventoryImport(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        file_name=(file_name or "import.xlsx")[:255],
        file_data=data,
        lang=lang.value,
        total_rows=len(rows),
    )
    db.add(record)
    await db.flush()
    db_job.enqueue(db, JobKind.INVENTORY_IMPORT, tenant_id, {"import_id": record.id}, max_attempts=3)
    await db.commit()
    return await get_import(db, tenant_id, record.id, lang)


def get_imports(tenant_id: int) -> Select:
    return (
        select(InventoryImport)
        .where(InventoryImport.tenant_id == tenant_id)
        .order_by(InventoryImport.created_at.desc(), InventoryImport.id.desc())
    )


async def get_import(
    db: AsyncSession, tenant_id: int, import_id: int, lang: Lang = DEFAULT_LANG
) -> InventoryImport:
    record = await db.scalar(
        select(InventoryImport).where(
            and_(InventoryImport.id == import_id, InventoryImport.tenant_id == tenant_id)
        ),
        execution_options={"populate_existing": True},
    )
    if record is None:
        raise generate_error(Msg.IMPORT_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return record
