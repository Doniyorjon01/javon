"""
Excel import job
================
Turns an uploaded sheet (services/excel.py) into shelf rows, one row at a time:

  1. find the book: by ISBN, or (no ISBN) by the edition key, among the books
     this store may see;
  2. not in the catalog -> submit it as a new pending book (source "import",
     its own pending limit, MAX_PENDING_BOOKS_FROM_IMPORT) — the store can sell
     it right away, as with a book added by hand;
  3. put it on the shelf, or update the shelf row: price and quantity are SET
     to what the file says.

Each row commits on its own, so one bad row never undoes the others, and
running the same file twice gives the same shelf (safe to retry). Problems are
collected per line in the report, in the language of the person who uploaded.
A store's own REJECTED book is not submitted again: the line reports it, with
the moderator's reason, instead of refilling the moderation queue.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_catalog, db_inventory
from models.catalog import Book, BookScript, BookSource, BookStatus
from models.inventory import MAX_PRICE, MAX_QUANTITY, ImportStatus, InventoryImport
from models.job import Job
from schemas.catalog import BookCreate
from services.excel import ExcelError, Row, parse_quantity, parse_som, read_rows, split_authors
from translations import Msg, translate
from utils.i18n import Lang
from utils.isbn import normalize_isbn
from utils.translit import book_dedupe_key, detect_script

logger = logging.getLogger(__name__)

MAX_REPORTED_ERRORS = 500
PROGRESS_EVERY = 50


class RowError(Exception):
    def __init__(self, msg: Msg | str, message: str) -> None:
        super().__init__(message)
        self.code = msg.value if isinstance(msg, Msg) else msg
        self.message = message


def _error(msg: Msg, lang: Lang, *values: object) -> RowError:
    text = translate(msg, lang)
    return RowError(msg, text.format(*values) if values else text)


async def _own_rejected(db: AsyncSession, tenant_id: int, data: BookCreate) -> Book | None:
    if data.isbn is not None:
        condition = Book.isbn13 == data.isbn
    else:
        script = data.script or BookScript(detect_script(data.title))
        condition = Book.dedupe_key == book_dedupe_key(
            language=data.language,
            script=script,
            title=data.title,
            subtitle=data.subtitle,
            authors=data.authors,
            publisher=data.publisher,
        )
    return await db.scalar(
        select(Book)
        .where(condition, Book.created_by_tenant_id == tenant_id, Book.status == BookStatus.REJECTED)
        .order_by(Book.id.desc())
        .limit(1)
    )


async def import_row(db: AsyncSession, tenant_id: int, row: Row, lang: Lang) -> tuple[bool, bool]:
    """Returns (book_created, item_added). Raises RowError."""
    values = row.values

    price = parse_som(values.get("price", ""))
    if price is None or price > MAX_PRICE:
        raise _error(Msg.IMPORT_ROW_BAD_PRICE, lang)
    quantity = parse_quantity(values["quantity"]) if "quantity" in values else 0
    if quantity is None or quantity > MAX_QUANTITY:
        raise _error(Msg.IMPORT_ROW_BAD_QUANTITY, lang)

    isbn13 = None
    if "isbn" in values:
        isbn13 = normalize_isbn(values["isbn"])
        if isbn13 is None:
            raise _error(Msg.INVALID_ISBN, lang, values["isbn"])

    book: Book | None = None
    if isbn13 is not None:
        book = await db_catalog.find_existing_book_by_isbn(db, tenant_id, isbn13)

    book_created = False
    if book is None:
        if "title" not in values or "authors" not in values:
            raise _error(Msg.IMPORT_ROW_BOOK_UNKNOWN, lang)
        fields: dict[str, Any] = {
            "isbn": isbn13,
            "title": values["title"],
            "authors": split_authors(values["authors"]),
            "publisher": values.get("publisher"),
        }
        for name in ("language", "script"):
            if name in values:
                fields[name] = values[name].lower()
        try:
            data = BookCreate(**fields)
        except ValidationError as exc:
            field = ".".join(str(part) for part in exc.errors()[0]["loc"])
            raise _error(Msg.IMPORT_ROW_INVALID, lang, field) from None

        if isbn13 is None:
            book = await db_catalog.find_existing_book(db, tenant_id, data)
        if book is None:
            rejected = await _own_rejected(db, tenant_id, data)
            if rejected is not None:
                raise _error(Msg.IMPORT_ROW_BOOK_REJECTED, lang, rejected.review_note or "-")
            try:
                book = await db_catalog.create_book(
                    db, data, tenant_id=tenant_id, source=BookSource.IMPORT, lang=lang
                )
            except HTTPException as exc:  # pending limit, ISBN held by another store's submission...
                raise RowError(exc.detail["code"], exc.detail["message"]) from None
            book_created = True

    try:
        added = await db_inventory.upsert_from_import(db, tenant_id, book.id, price, quantity, lang)
    except HTTPException as exc:  # the plan's book limit
        raise RowError(exc.detail["code"], exc.detail["message"]) from None
    return book_created, added


async def _save_progress(db: AsyncSession, record: InventoryImport, processed: int) -> None:
    record.processed_rows = processed
    await db.commit()


async def run(db: AsyncSession, job: Job) -> None:
    """The job handler. The session is already bound to job.tenant_id."""
    tenant_id = job.tenant_id
    if tenant_id is None:
        raise RuntimeError("inventory_import job without tenant_id")
    record = await db.scalar(
        select(InventoryImport).where(
            InventoryImport.id == job.payload["import_id"], InventoryImport.tenant_id == tenant_id
        )
    )
    if record is None or record.status in (ImportStatus.DONE, ImportStatus.FAILED):
        return  # nothing to do (already finished by an earlier attempt)
    lang = Lang(record.lang) if record.lang in Lang.__members__.values() else Lang.uz
    record.status = ImportStatus.RUNNING
    await db.commit()

    try:
        rows = await asyncio.to_thread(read_rows, record.file_data or b"", settings.MAX_IMPORT_ROWS)
    except ExcelError as exc:
        record.status = ImportStatus.FAILED
        record.report = {"error": exc.problem.value}
        record.file_data = None
        record.finished_at = datetime.now(UTC)
        await db.commit()
        return

    record_id = record.id
    counters = {"books_matched": 0, "books_created": 0, "items_added": 0, "items_updated": 0}
    errors: list[dict[str, Any]] = []
    for processed, row in enumerate(rows, start=1):
        try:
            book_created, item_added = await import_row(db, tenant_id, row, lang)
        except RowError as exc:
            await db.rollback()
            if len(errors) < MAX_REPORTED_ERRORS:
                errors.append({"line": row.line, "code": exc.code, "message": exc.message})
        else:
            counters["books_created" if book_created else "books_matched"] += 1
            counters["items_added" if item_added else "items_updated"] += 1
        if processed % PROGRESS_EVERY == 0:
            record = await db_inventory.get_import(db, tenant_id, record_id)
            await _save_progress(db, record, processed)

    record = await db_inventory.get_import(db, tenant_id, record_id)
    record.status = ImportStatus.DONE
    record.processed_rows = len(rows)
    record.total_rows = len(rows)
    failed = len(rows) - counters["items_added"] - counters["items_updated"]
    record.report = {
        **counters,
        "failed_rows": failed,
        "errors": errors,
        "errors_truncated": failed > len(errors),
    }
    record.file_data = None
    record.finished_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "Inventory import finished",
        extra={"tenant_id": tenant_id, "import_id": record_id, "rows": len(rows), "failed": failed},
    )
