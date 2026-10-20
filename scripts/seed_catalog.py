"""
Load books into the shared catalog from a CSV file
==================================================
    python -m scripts.seed_catalog books.csv            # from the project root
    python -m scripts.seed_catalog books.csv --dry-run  # check the file, write nothing

Books are added as APPROVED (visible to every store) with no submitting store.
Safe to run again on the same file: a row whose ISBN is already in the catalog,
or an ISBN-less row whose edition is already there (same title, authors,
publisher, language and script — books.dedupe_key), is skipped.

CSV: UTF-8, comma-separated, first line is the header. Columns:
    title            required
    authors          required; several authors separated by ";"
    isbn             ISBN-10 or ISBN-13, hyphens allowed; may be empty
    subtitle, publisher, language (uz|ru|en|other, default uz),
    script (latn|cyrl|other; detected from the title when empty),
    published_year, pages, description, mxik_code (17 digits), package_code
Unknown columns are ignored. Empty cells mean "not known".

Uses DATABASE_URL from .env, like the API. A bad row is reported with its line
number and skipped; the rest of the file is still loaded.
"""

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_catalog
from database.config import SessionLocal, engine
from models.catalog import Book, BookScript, BookStatus
from schemas.catalog import BookCreate
from utils.translit import book_dedupe_key, detect_script

FIELDS = (
    "isbn", "title", "subtitle", "authors", "publisher", "language", "script",
    "published_year", "pages", "description", "mxik_code", "package_code",
)  # fmt: skip


@dataclass
class Report:
    added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def parse_row(row: dict[str, str | None]) -> BookCreate:
    """One CSV row -> validated BookCreate. Raises ValidationError with the reason."""
    data: dict[str, object] = {}
    for name in FIELDS:
        value = (row.get(name) or "").strip()
        if value:
            data[name] = value
    if "authors" in data:
        data["authors"] = [a.strip() for a in str(data["authors"]).split(";") if a.strip()]
    return BookCreate(**data)


async def _already_loaded(db: AsyncSession, book: BookCreate) -> bool:
    if book.isbn:
        return await db.scalar(select(Book.id).where(Book.isbn13 == book.isbn).limit(1)) is not None
    key = book_dedupe_key(
        language=book.language,
        script=book.script or BookScript(detect_script(book.title)),
        title=book.title,
        subtitle=book.subtitle,
        authors=book.authors,
        publisher=book.publisher,
    )
    found = await db.scalar(
        select(Book.id).where(Book.dedupe_key == key, Book.status != BookStatus.REJECTED).limit(1)
    )
    return found is not None


async def load(path: Path, *, dry_run: bool = False) -> Report:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return await load_rows(rows, dry_run=dry_run, first=2, where="line")  # line 1 is the header


async def load_rows(
    rows: list[dict[str, str | None]], *, dry_run: bool = False, first: int = 1, where: str = "row"
) -> Report:
    """The CSV columns as dicts (also used by scripts/seed_starter_books.py)."""
    report = Report()
    async with SessionLocal() as db:
        for line_no, row in enumerate(rows, start=first):
            try:
                book = parse_row(row)
            except ValidationError as exc:
                reasons = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                report.errors.append(f"{where} {line_no}: {reasons}")
                continue

            if await _already_loaded(db, book):
                report.skipped += 1
                continue
            if dry_run:
                report.added += 1
                continue
            try:
                await db_catalog.create_book(db, book, tenant_id=None, book_status=BookStatus.APPROVED)
                report.added += 1
            except HTTPException as exc:  # e.g. the same ISBN twice in one file
                report.errors.append(f"{where} {line_no}: {exc.detail['message']}")
    return report


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Load books into the javon catalog from CSV.")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    args = parser.parse_args(argv)

    if not args.csv_file.is_file():
        print(f"File not found: {args.csv_file}", file=sys.stderr)
        return 2
    try:
        report = await load(args.csv_file, dry_run=args.dry_run)
    finally:
        await engine.dispose()

    verb = "would be added" if args.dry_run else "added"
    print(f"{report.added} {verb}, {report.skipped} already in the catalog, {len(report.errors)} errors")
    for error in report.errors:
        print("  " + error, file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
