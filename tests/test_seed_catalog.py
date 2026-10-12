from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Book, BookStatus
from scripts.seed_catalog import load, parse_row

CSV = """title,authors,isbn,publisher,language,published_year,extra_column
O'tkan kunlar,Abdulla Qodiriy,978-0-306-40615-7,Sharq,uz,2019,ignored
Преступление и наказание,Фёдор Достоевский,,,ru,,
Ikki muallif,Birinchi Muallif; Ikkinchi Muallif,,,uz,,
Yomon ISBN,Kimdir,9780306406158,,uz,,
,Sarlavhasiz,,,uz,,
Yomon yil,Kimdir,,,uz,1200,
"""


def test_parse_row_splits_authors_and_ignores_empty_cells() -> None:
    book = parse_row({"title": "Ikki muallif", "authors": "A Bir; B Ikki ;", "isbn": " ", "pages": ""})
    assert book.authors == ["A Bir", "B Ikki"]
    assert book.isbn is None
    assert book.pages is None


def test_parse_row_reports_bad_isbn() -> None:
    with pytest.raises(ValidationError, match="ISBN"):
        parse_row({"title": "X", "authors": "Y", "isbn": "123"})


@pytest.mark.db
async def test_load_is_idempotent_and_reports_bad_lines(tmp_path: Path, db: AsyncSession) -> None:
    path = tmp_path / "books.csv"
    path.write_text(CSV, encoding="utf-8")

    dry = await load(path, dry_run=True)
    assert (dry.added, dry.skipped) == (3, 0)
    assert await db.scalar(select(func.count()).select_from(Book)) == 0

    first = await load(path)
    assert (first.added, first.skipped) == (3, 0)
    assert [e.split(":")[0] for e in first.errors] == ["line 5", "line 6", "line 7"]

    statuses = set(await db.scalars(select(Book.status)))
    assert statuses == {BookStatus.APPROVED}

    second = await load(path)
    assert (second.added, second.skipped) == (0, 3)
    assert await db.scalar(select(func.count()).select_from(Book)) == 3
