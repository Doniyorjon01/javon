"""
Catalog — database layer
========================
Platform-level tables (no RLS), so every store-facing query here carries an
explicit visibility filter: approved books, plus the asking store's own pending
ones (see models/catalog.py). A store may also open its own rejected books, to
read the moderator's note, but never finds them in search. Moderation functions
(the platform admin) see all.

Every write goes through _set_derived(), so books.search_text and
books.dedupe_key always reflect the data actually stored.

Store submissions are limited: at most settings.MAX_PENDING_BOOKS_PER_STORE
waiting for moderation, and an ISBN-less book that is already in the catalog is
refused with its id (409 book_duplicate), so the store picks the existing one.
"""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import ColumnElement, Select, and_, delete, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database.integrity import constraint_name
from errors import generate_error
from models.catalog import Author, Book, BookAuthor, BookScript, BookSource, BookStatus, Publisher
from models.tenant import Tenant
from schemas.catalog import BookCreate, BookUpdate
from services.media import delete_image, save_image
from services.storage import Storage
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.images import COVER_SPEC
from utils.isbn import looks_like_isbn, normalize_isbn
from utils.translit import book_dedupe_key, detect_script, search_key

ISBN_UNIQUE_INDEX = "uq_books_isbn13_live"
MIN_QUERY_LENGTH = 2


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def visible_to(tenant_id: int) -> ColumnElement[bool]:
    return and_(
        Book.is_active.is_(True),
        or_(
            Book.status == BookStatus.APPROVED,
            and_(Book.status == BookStatus.PENDING, Book.created_by_tenant_id == tenant_id),
        ),
    )


def _readable_by(tenant_id: int) -> ColumnElement[bool]:
    """What a store may open by id: what it sees, plus its own rejected books."""
    return or_(
        visible_to(tenant_id),
        and_(
            Book.is_active.is_(True),
            Book.status == BookStatus.REJECTED,
            Book.created_by_tenant_id == tenant_id,
        ),
    )


def _with_relations(stmt: Select) -> Select:
    return stmt.options(selectinload(Book.authors), selectinload(Book.publisher))


def search_books(tenant_id: int, query: str, lang: Lang = DEFAULT_LANG) -> Select:
    """
    Books matching `query` that this store may see, best match first.
    An ISBN (with or without hyphens, ISBN-10 or -13) is matched exactly;
    anything else by words, in Latin or Cyrillic, tolerating small typos.
    """
    stmt = _with_relations(select(Book).where(visible_to(tenant_id)))

    if looks_like_isbn(query):
        isbn13 = normalize_isbn(query)
        return stmt.where(Book.isbn13 == isbn13 if isbn13 else false()).order_by(Book.id)

    key = search_key(query)
    if len(key) < MIN_QUERY_LENGTH:
        raise generate_error(Msg.SEARCH_QUERY_TOO_SHORT, lang)

    # `<%` = word similarity above pg_trgm.word_similarity_threshold (0.6): typos.
    # LIKE  = the exact words appear somewhere: short or partial words.
    # Both are served by the trigram GIN index. `key` holds only [a-z0-9 ].
    typo_tolerant = literal(key).op("<%", is_comparison=True)(Book.search_text)
    return stmt.where(or_(typo_tolerant, Book.search_text.contains(key))).order_by(
        func.word_similarity(key, Book.search_text).desc(), Book.title, Book.id
    )


async def get_book(db: AsyncSession, tenant_id: int, book_id: int, lang: Lang = DEFAULT_LANG) -> Book:
    book = await db.scalar(_with_relations(select(Book).where(Book.id == book_id, _readable_by(tenant_id))))
    if book is None:
        raise generate_error(Msg.BOOK_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return book


def get_submissions(tenant_id: int, book_status: BookStatus | None = None) -> Select:
    """Books this store added, newest first; rejected ones carry the moderator's note."""
    stmt = select(Book).where(Book.created_by_tenant_id == tenant_id, Book.is_active.is_(True))
    if book_status is not None:
        stmt = stmt.where(Book.status == book_status)
    return _with_relations(stmt).order_by(Book.created_at.desc(), Book.id.desc())


async def get_book_by_isbn(
    db: AsyncSession, tenant_id: int, raw_isbn: str, lang: Lang = DEFAULT_LANG
) -> Book:
    """For the barcode scanner. 404 means "not in the catalog yet: offer to add it"."""
    isbn13 = normalize_isbn(raw_isbn)
    if isbn13 is None:
        raise generate_error(Msg.INVALID_ISBN, lang, format_values=(raw_isbn,))
    book = await db.scalar(_with_relations(select(Book).where(Book.isbn13 == isbn13, visible_to(tenant_id))))
    if book is None:
        raise generate_error(
            Msg.BOOK_ISBN_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND, format_values=(isbn13,)
        )
    return book


def get_books_for_review(book_status: BookStatus) -> Select:
    """Moderation list, oldest first. Platform admin only."""
    return _with_relations(select(Book).where(Book.status == book_status, Book.is_active.is_(True))).order_by(
        Book.created_at, Book.id
    )


async def find_existing_book_by_isbn(db: AsyncSession, tenant_id: int, isbn13: str) -> Book | None:
    return await db.scalar(select(Book).where(Book.isbn13 == isbn13, visible_to(tenant_id)))


async def find_existing_book(db: AsyncSession, tenant_id: int, data: BookCreate) -> Book | None:
    """
    The catalog record this store would use for `data`, if any: the same ISBN,
    or (without an ISBN) the same edition by dedupe_key. Excel import uses it to
    decide between "match" and "create".
    """
    if data.isbn is not None:
        return await find_existing_book_by_isbn(db, tenant_id, data.isbn)
    else:
        script = data.script or BookScript(detect_script(data.title))
        key = _dedupe_key(data, script, data.authors, data.publisher)
        stmt = (
            select(Book)
            .where(Book.dedupe_key == key, Book.status != BookStatus.REJECTED, visible_to(tenant_id))
            .order_by(Book.id)
            .limit(1)
        )
    return await db.scalar(stmt)


async def get_any_book(db: AsyncSession, book_id: int, lang: Lang = DEFAULT_LANG) -> Book:
    """Any status. Platform admin only."""
    book = await db.scalar(
        _with_relations(select(Book).where(Book.id == book_id, Book.is_active.is_(True))),
        execution_options={"populate_existing": True},
    )
    if book is None:
        raise generate_error(Msg.BOOK_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return book


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
async def _get_or_create_author(db: AsyncSession, name: str) -> Author:
    """One author per search key. The first spelling stored is kept."""
    key = search_key(name)
    await db.execute(
        pg_insert(Author)
        .values(name=name, search_key=key)
        .on_conflict_do_nothing(index_elements=[Author.search_key])
    )
    return (await db.scalars(select(Author).where(Author.search_key == key))).one()


async def _get_or_create_publisher(db: AsyncSession, name: str) -> Publisher:
    key = search_key(name)
    await db.execute(
        pg_insert(Publisher)
        .values(name=name, search_key=key)
        .on_conflict_do_nothing(index_elements=[Publisher.search_key])
    )
    return (await db.scalars(select(Publisher).where(Publisher.search_key == key))).one()


async def _set_authors(db: AsyncSession, book: Book, names: list[str]) -> list[Author]:
    authors = [await _get_or_create_author(db, name) for name in names]
    await db.execute(delete(BookAuthor).where(BookAuthor.book_id == book.id))
    db.add_all(
        BookAuthor(book_id=book.id, author_id=author.id, position=position)
        for position, author in enumerate(authors)
    )
    return authors


def _dedupe_key(
    book: Book | BookCreate, script: BookScript, authors: list[str], publisher: str | None
) -> str:
    return book_dedupe_key(
        language=book.language,
        script=script,
        title=book.title,
        subtitle=book.subtitle,
        authors=authors,
        publisher=publisher,
    )


def _set_derived(book: Book, authors: list[Author], publisher: Publisher | None) -> None:
    """search_text and dedupe_key from what is stored now."""
    names = [author.name for author in authors]
    publisher_name = publisher.name if publisher else None
    book.search_text = search_key(book.title, book.subtitle, *names, publisher_name, book.isbn13)
    book.dedupe_key = _dedupe_key(book, book.script, names, publisher_name)


PENDING_LIMITS = {
    BookSource.MANUAL: lambda: settings.MAX_PENDING_BOOKS_PER_STORE,
    BookSource.IMPORT: lambda: settings.MAX_PENDING_BOOKS_FROM_IMPORT,
}


async def _check_submission_allowed(db: AsyncSession, tenant_id: int, source: BookSource, lang: Lang) -> None:
    """
    At most MAX_PENDING_BOOKS_PER_STORE books added by hand, and at most
    MAX_PENDING_BOOKS_FROM_IMPORT from Excel files, waiting for moderation per
    store (counted separately: a big import must not block adding one book).
    The store's row is locked until commit, so one store's submissions are
    counted one at a time (parallel requests cannot all slip under the limit)
    and the duplicate check after this one cannot race either.
    """
    await db.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update(key_share=True))
    pending = await db.scalar(
        select(func.count())
        .select_from(Book)
        .where(
            Book.created_by_tenant_id == tenant_id,
            Book.submitted_via == source,
            Book.status == BookStatus.PENDING,
            Book.is_active.is_(True),
        )
    )
    limit = PENDING_LIMITS[source]()
    if pending >= limit:
        await db.rollback()
        raise generate_error(Msg.PENDING_BOOKS_LIMIT, lang, status.HTTP_409_CONFLICT, format_values=(limit,))


async def _find_duplicate(db: AsyncSession, key: str, tenant_id: int | None) -> int | None:
    """An existing record of the same ISBN-less edition that the caller can see."""
    visible = visible_to(tenant_id) if tenant_id is not None else Book.is_active.is_(True)
    return await db.scalar(
        select(Book.id)
        .where(Book.dedupe_key == key, Book.status != BookStatus.REJECTED, visible)
        .order_by(Book.id)
        .limit(1)
    )


async def _commit_or_isbn_conflict(db: AsyncSession, isbn13: str | None, lang: Lang) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if constraint_name(exc) == ISBN_UNIQUE_INDEX:
            raise generate_error(
                Msg.BOOK_ISBN_EXISTS, lang, status.HTTP_409_CONFLICT, format_values=(isbn13,)
            ) from exc
        raise


async def create_book(
    db: AsyncSession,
    data: BookCreate,
    *,
    tenant_id: int | None,
    book_status: BookStatus = BookStatus.PENDING,
    source: BookSource = BookSource.MANUAL,
    lang: Lang = DEFAULT_LANG,
) -> Book:
    """
    A store's submission (tenant_id set, PENDING; `source` says how) or a
    platform import (tenant_id None, usually APPROVED). One transaction: book,
    authors, publisher.
    """
    script = data.script or BookScript(detect_script(data.title))
    if tenant_id is not None:
        await _check_submission_allowed(db, tenant_id, source, lang)
    if data.isbn is None:  # with an ISBN the unique index decides
        duplicate_id = await _find_duplicate(
            db, _dedupe_key(data, script, data.authors, data.publisher), tenant_id
        )
        if duplicate_id is not None:
            await db.rollback()
            raise generate_error(
                Msg.BOOK_DUPLICATE, lang, status.HTTP_409_CONFLICT, extra={"book_id": duplicate_id}
            )

    publisher = await _get_or_create_publisher(db, data.publisher) if data.publisher else None
    book = Book(
        isbn13=data.isbn,
        title=data.title,
        subtitle=data.subtitle,
        publisher_id=publisher.id if publisher else None,
        language=data.language,
        script=script,
        published_year=data.published_year,
        pages=data.pages,
        description=data.description,
        mxik_code=data.mxik_code,
        package_code=data.package_code,
        status=book_status,
        created_by_tenant_id=tenant_id,
        submitted_via=source if tenant_id is not None else None,
        search_text="-",  # both replaced by _set_derived() once the authors are known
        dedupe_key="-",
    )
    db.add(book)
    try:
        await db.flush()  # assigns book.id; a duplicate ISBN fails here
    except IntegrityError as exc:
        await db.rollback()
        if constraint_name(exc) == ISBN_UNIQUE_INDEX:
            raise generate_error(
                Msg.BOOK_ISBN_EXISTS, lang, status.HTTP_409_CONFLICT, format_values=(data.isbn,)
            ) from exc
        raise
    authors = await _set_authors(db, book, data.authors)
    _set_derived(book, authors, publisher)
    await _commit_or_isbn_conflict(db, data.isbn, lang)
    return await get_any_book(db, book.id, lang)


async def update_book(db: AsyncSession, book_id: int, data: BookUpdate, lang: Lang = DEFAULT_LANG) -> Book:
    """Moderator's correction. Only the fields sent change; search_text and dedupe_key are rebuilt."""
    book = await get_any_book(db, book_id, lang)
    changes = data.model_dump(exclude_unset=True)

    for required in ("title", "language", "script", "authors"):
        if required in changes and changes[required] is None:
            changes.pop(required)  # these cannot be cleared, only replaced
    if "isbn" in changes:
        book.isbn13 = changes.pop("isbn")
    authors = list(book.authors)
    if "authors" in changes:
        authors = await _set_authors(db, book, changes.pop("authors"))
    publisher = book.publisher
    if "publisher" in changes:
        name = changes.pop("publisher")
        publisher = await _get_or_create_publisher(db, name) if name else None
        book.publisher_id = publisher.id if publisher else None
    for field, value in changes.items():
        setattr(book, field, value)

    _set_derived(book, authors, publisher)
    await _commit_or_isbn_conflict(db, book.isbn13, lang)
    return await get_any_book(db, book.id, lang)


async def set_book_status(
    db: AsyncSession,
    book_id: int,
    book_status: BookStatus,
    lang: Lang = DEFAULT_LANG,
    *,
    note: str | None = None,
) -> Book:
    """Approve or reject. `note` is the reason for a rejection; approving clears it."""
    book = await get_any_book(db, book_id, lang)
    book.status = book_status
    book.review_note = note if book_status == BookStatus.REJECTED else None
    book.reviewed_at = datetime.now(UTC)
    # Approving a rejected book can collide with a newer record of the same ISBN.
    await _commit_or_isbn_conflict(db, book.isbn13, lang)
    return await get_any_book(db, book.id, lang)


# --------------------------------------------------------------------------- #
# Covers
# --------------------------------------------------------------------------- #
async def set_cover(
    db: AsyncSession,
    storage: Storage,
    book_id: int,
    data: bytes,
    lang: Lang = DEFAULT_LANG,
    *,
    tenant_id: int | None,
) -> Book:
    """
    Replace a book's cover. A store (tenant_id set) may only illustrate a book it
    submitted and that is still waiting for moderation; once approved, the cover
    is shared by every store and only the platform admin (tenant_id None) changes it.
    """
    if tenant_id is None:
        book = await get_any_book(db, book_id, lang)
    else:
        book = await get_book(db, tenant_id, book_id, lang)
        if book.created_by_tenant_id != tenant_id or book.status != BookStatus.PENDING:
            raise generate_error(Msg.COVER_NOT_ALLOWED, lang, status.HTTP_403_FORBIDDEN)
    await db.rollback()  # do not hold the transaction open during the upload

    new_key = await save_image(storage, f"covers/{book_id}", data, COVER_SPEC, lang)
    book = await db.get(Book, book_id, with_for_update=True, populate_existing=True)
    if book is None:  # pragma: no cover — books are never deleted
        await delete_image(storage, new_key, COVER_SPEC)
        raise generate_error(Msg.BOOK_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    old_key, book.cover_key = book.cover_key, new_key
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await delete_image(storage, new_key, COVER_SPEC)
        raise
    await delete_image(storage, old_key, COVER_SPEC)
    return await get_any_book(db, book_id, lang)


async def delete_cover(db: AsyncSession, storage: Storage, book_id: int, lang: Lang = DEFAULT_LANG) -> Book:
    """Platform admin only."""
    book = await get_any_book(db, book_id, lang)
    old_key, book.cover_key = book.cover_key, None
    await db.commit()
    await delete_image(storage, old_key, COVER_SPEC)
    return await get_any_book(db, book_id, lang)
