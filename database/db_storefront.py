"""
Storefront — database layer (public, read-only)
===============================================
What a buyer may see in one store: shelf rows that are live and visible, whose
book this store may sell (approved, or the store's own pending submission —
the same rule as db_catalog.visible_to). Out-of-stock books are listed too,
marked in_stock = false: "we usually have it" is useful to a buyer.

The session is bound to the store (auth/tenant.get_storefront_tenant) so RLS
applies; every query still filters by tenant_id explicitly.
"""

from fastapi import status
from sqlalchemy import ColumnElement, Select, and_, exists, false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.db_catalog import MIN_QUERY_LENGTH, visible_to
from errors import generate_error
from models.catalog import Author, Book, BookAuthor, BookLanguage, BookScript, Publisher
from models.inventory import InventoryItem
from schemas.storefront import FacetEntity, FacetsOut, FacetValue, SitemapEntry, StorefrontSort
from translations import Msg
from utils.i18n import DEFAULT_LANG, Lang
from utils.isbn import looks_like_isbn, normalize_isbn
from utils.translit import search_key

SIMILAR_LIMIT = 8
FACET_LIMIT = 30
SITEMAP_LIMIT = 50_000  # one sitemap file holds at most 50 000 URLs


def listed(tenant_id: int) -> ColumnElement[bool]:
    return and_(
        InventoryItem.tenant_id == tenant_id,
        InventoryItem.is_active.is_(True),
        InventoryItem.is_visible.is_(True),
        visible_to(tenant_id),
    )


def _base(tenant_id: int) -> Select:
    return (
        select(InventoryItem)
        .join(Book, Book.id == InventoryItem.book_id)
        .where(listed(tenant_id))
        .options(
            selectinload(InventoryItem.book).selectinload(Book.authors),
            selectinload(InventoryItem.book).selectinload(Book.publisher),
        )
    )


def get_items(
    tenant_id: int,
    *,
    query: str | None = None,
    language: BookLanguage | None = None,
    script: BookScript | None = None,
    author_id: int | None = None,
    publisher_id: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    in_stock: bool | None = None,
    sort: StorefrontSort | None = None,
    lang: Lang = DEFAULT_LANG,
) -> Select:
    stmt = _base(tenant_id)
    relevance = None

    if query:
        if looks_like_isbn(query):
            isbn13 = normalize_isbn(query)
            stmt = stmt.where(Book.isbn13 == isbn13 if isbn13 else false())
        else:
            key = search_key(query)
            if len(key) < MIN_QUERY_LENGTH:
                raise generate_error(Msg.SEARCH_QUERY_TOO_SHORT, lang)
            typo_tolerant = literal(key).op("<%", is_comparison=True)(Book.search_text)
            stmt = stmt.where(or_(typo_tolerant, Book.search_text.contains(key)))
            relevance = func.word_similarity(key, Book.search_text).desc()

    if language is not None:
        stmt = stmt.where(Book.language == language)
    if script is not None:
        stmt = stmt.where(Book.script == script)
    if author_id is not None:
        stmt = stmt.where(exists().where(BookAuthor.book_id == Book.id, BookAuthor.author_id == author_id))
    if publisher_id is not None:
        stmt = stmt.where(Book.publisher_id == publisher_id)
    if min_price is not None:
        stmt = stmt.where(InventoryItem.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(InventoryItem.price <= max_price)
    if in_stock is not None:
        stmt = stmt.where(InventoryItem.quantity > 0 if in_stock else InventoryItem.quantity == 0)

    if sort is None:
        sort = StorefrontSort.RELEVANCE if relevance is not None else StorefrontSort.NEW
    order = {
        StorefrontSort.NEW: [InventoryItem.created_at.desc()],
        StorefrontSort.PRICE_ASC: [InventoryItem.price],
        StorefrontSort.PRICE_DESC: [InventoryItem.price.desc()],
        StorefrontSort.TITLE: [Book.title],
        StorefrontSort.RELEVANCE: [relevance] if relevance is not None else [InventoryItem.created_at.desc()],
    }[sort]
    return stmt.order_by(*order, InventoryItem.id.desc())


async def get_item(
    db: AsyncSession, tenant_id: int, book_id: int, lang: Lang = DEFAULT_LANG
) -> InventoryItem:
    item = await db.scalar(_base(tenant_id).where(InventoryItem.book_id == book_id))
    if item is None:
        raise generate_error(Msg.BOOK_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)
    return item


async def get_similar(db: AsyncSession, tenant_id: int, item: InventoryItem) -> list[InventoryItem]:
    """Same author(s) first, then the same publisher; in stock first."""
    in_stock_first = (InventoryItem.quantity > 0).desc()
    author_ids = [author.id for author in item.book.authors]
    found: list[InventoryItem] = []
    if author_ids:
        same_author = exists().where(BookAuthor.book_id == Book.id, BookAuthor.author_id.in_(author_ids))
        found = list(
            await db.scalars(
                _base(tenant_id)
                .where(same_author, InventoryItem.book_id != item.book_id)
                .order_by(in_stock_first, InventoryItem.created_at.desc(), InventoryItem.id.desc())
                .limit(SIMILAR_LIMIT)
            )
        )
    if len(found) < SIMILAR_LIMIT and item.book.publisher_id is not None:
        seen = [item.book_id, *(other.book_id for other in found)]
        found += list(
            await db.scalars(
                _base(tenant_id)
                .where(Book.publisher_id == item.book.publisher_id, InventoryItem.book_id.not_in(seen))
                .order_by(in_stock_first, InventoryItem.created_at.desc(), InventoryItem.id.desc())
                .limit(SIMILAR_LIMIT - len(found))
            )
        )
    return found


async def get_facets(db: AsyncSession, tenant_id: int) -> FacetsOut:
    listed_books = (
        select(InventoryItem.book_id.label("book_id"), InventoryItem.price.label("price"))
        .join(Book, Book.id == InventoryItem.book_id)
        .where(listed(tenant_id))
        .subquery()
    )
    totals = (
        await db.execute(select(func.count(), func.min(listed_books.c.price), func.max(listed_books.c.price)))
    ).one()

    async def _values(column: ColumnElement) -> list[FacetValue]:
        rows = await db.execute(
            select(column, func.count())
            .select_from(listed_books)
            .join(Book, Book.id == listed_books.c.book_id)
            .group_by(column)
            .order_by(func.count().desc(), column)
        )
        return [FacetValue(value=str(value), count=count) for value, count in rows]

    author_rows = await db.execute(
        select(Author.id, Author.name, func.count())
        .select_from(listed_books)
        .join(BookAuthor, BookAuthor.book_id == listed_books.c.book_id)
        .join(Author, Author.id == BookAuthor.author_id)
        .group_by(Author.id, Author.name)
        .order_by(func.count().desc(), Author.name)
        .limit(FACET_LIMIT)
    )
    publisher_rows = await db.execute(
        select(Publisher.id, Publisher.name, func.count())
        .select_from(listed_books)
        .join(Book, Book.id == listed_books.c.book_id)
        .join(Publisher, Publisher.id == Book.publisher_id)
        .group_by(Publisher.id, Publisher.name)
        .order_by(func.count().desc(), Publisher.name)
        .limit(FACET_LIMIT)
    )
    return FacetsOut(
        total=totals[0],
        languages=await _values(Book.language),
        scripts=await _values(Book.script),
        authors=[FacetEntity(id=i, name=n, count=c) for i, n, c in author_rows],
        publishers=[FacetEntity(id=i, name=n, count=c) for i, n, c in publisher_rows],
        price_min=totals[1],
        price_max=totals[2],
    )


async def get_sitemap(db: AsyncSession, tenant_id: int) -> list[SitemapEntry]:
    rows = await db.execute(
        select(InventoryItem.book_id, func.greatest(InventoryItem.updated_at, Book.updated_at))
        .join(Book, Book.id == InventoryItem.book_id)
        .where(listed(tenant_id))
        .order_by(InventoryItem.book_id)
        .limit(SITEMAP_LIMIT)
    )
    return [SitemapEntry(book_id=book_id, updated_at=updated_at) for book_id, updated_at in rows]
