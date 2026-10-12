"""
Catalog — database layer
========================
Platform-level tables (no RLS), so every store-facing query here carries an
explicit visibility filter: approved books, plus the asking store's own pending
ones (see models/catalog.py). Moderation functions (the platform admin) see all.

Every write goes through _set_search_text(), so books.search_text always
reflects the title, authors, publisher and ISBN actually stored.
"""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import ColumnElement, Select, and_, delete, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.integrity import constraint_name
from errors import generate_error
from models.catalog import Author, Book, BookAuthor, BookStatus, Publisher
from schemas.catalog import BookCreate, BookUpdate
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.isbn import looks_like_isbn, normalize_isbn
from utils.translit import search_key

ISBN_UNIQUE_INDEX = "uq_books_isbn13_live"
MIN_QUERY_LENGTH = 2


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def _visible_to(tenant_id: int) -> ColumnElement[bool]:
    return and_(
        Book.is_active.is_(True),
        or_(
            Book.status == BookStatus.APPROVED,
            and_(Book.status == BookStatus.PENDING, Book.created_by_tenant_id == tenant_id),
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
    stmt = _with_relations(select(Book).where(_visible_to(tenant_id)))

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
    book = await db.scalar(_with_relations(select(Book).where(Book.id == book_id, _visible_to(tenant_id))))
    if book is None:
        raise generate_error(Msg.BOOK_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return book


async def get_book_by_isbn(
    db: AsyncSession, tenant_id: int, raw_isbn: str, lang: Lang = DEFAULT_LANG
) -> Book:
    """For the barcode scanner. 404 means "not in the catalog yet: offer to add it"."""
    isbn13 = normalize_isbn(raw_isbn)
    if isbn13 is None:
        raise generate_error(Msg.INVALID_ISBN, lang, format_values=(raw_isbn,))
    book = await db.scalar(_with_relations(select(Book).where(Book.isbn13 == isbn13, _visible_to(tenant_id))))
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


def _set_search_text(book: Book, authors: list[Author], publisher: Publisher | None) -> None:
    book.search_text = search_key(
        book.title,
        book.subtitle,
        *(author.name for author in authors),
        publisher.name if publisher else None,
        book.isbn13,
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
    lang: Lang = DEFAULT_LANG,
) -> Book:
    """
    A store's submission (tenant_id set, PENDING) or a platform import
    (tenant_id None, usually APPROVED). One transaction: book, authors, publisher.
    """
    publisher = await _get_or_create_publisher(db, data.publisher) if data.publisher else None
    book = Book(
        isbn13=data.isbn,
        title=data.title,
        subtitle=data.subtitle,
        publisher_id=publisher.id if publisher else None,
        language=data.language,
        published_year=data.published_year,
        pages=data.pages,
        description=data.description,
        mxik_code=data.mxik_code,
        status=book_status,
        created_by_tenant_id=tenant_id,
        search_text="-",  # replaced below, once the authors are known
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
    _set_search_text(book, authors, publisher)
    await _commit_or_isbn_conflict(db, data.isbn, lang)
    return await get_any_book(db, book.id, lang)


async def update_book(db: AsyncSession, book_id: int, data: BookUpdate, lang: Lang = DEFAULT_LANG) -> Book:
    """Moderator's correction. Only the fields sent change; search_text is rebuilt."""
    book = await get_any_book(db, book_id, lang)
    changes = data.model_dump(exclude_unset=True)

    for required in ("title", "language", "authors"):
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

    _set_search_text(book, authors, publisher)
    await _commit_or_isbn_conflict(db, book.isbn13, lang)
    return await get_any_book(db, book.id, lang)


async def set_book_status(
    db: AsyncSession, book_id: int, book_status: BookStatus, lang: Lang = DEFAULT_LANG
) -> Book:
    book = await get_any_book(db, book_id, lang)
    book.status = book_status
    book.reviewed_at = datetime.now(UTC)
    # Approving a rejected book can collide with a newer record of the same ISBN.
    await _commit_or_isbn_conflict(db, book.isbn13, lang)
    return await get_any_book(db, book.id, lang)
