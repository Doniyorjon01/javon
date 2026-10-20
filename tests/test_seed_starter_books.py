import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Book, BookStatus
from scripts.seed_catalog import parse_row
from scripts.seed_starter_books import STARTER_BOOKS, UZBEK_CLASSICS, load


def test_every_starter_book_is_valid_and_unique() -> None:
    books = [parse_row(row) for row in STARTER_BOOKS + UZBEK_CLASSICS]
    isbns = [book.isbn for book in books if book.isbn]
    assert len(isbns) == len(STARTER_BOOKS) >= 50
    assert len(set(isbns)) == len(isbns)
    titles = [(book.title, tuple(book.authors)) for book in books]
    assert len(set(titles)) == len(titles)


@pytest.mark.db
async def test_load_twice_adds_once(db: AsyncSession) -> None:
    total = len(STARTER_BOOKS) + len(UZBEK_CLASSICS)
    first = await load()
    assert (first.added, first.skipped, first.errors) == (total, 0, [])
    assert set(await db.scalars(select(Book.status))) == {BookStatus.APPROVED}

    second = await load()
    assert (second.added, second.skipped) == (0, total)
    assert await db.scalar(select(func.count()).select_from(Book)) == total
