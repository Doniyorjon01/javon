"""store rules and book fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 12:00:00+05:00

users.max_stores     how many stores an account may own (1; the admin raises it)
tenants.launched_at  the storefront is public only after the owner launches it.
                     Stores that already exist were public, so they count as
                     launched at creation.
books.script         Latin / Cyrillic edition; filled from the title for
                     existing rows (utils/translit.detect_script)
books.package_code   fiscal receipt package code (with mxik_code)
books.review_note    why the moderator rejected the book
books.dedupe_key     identity of an ISBN-less edition (utils/translit.book_dedupe_key),
                     computed here for existing rows

The backfill imports utils.translit on purpose: it must produce exactly what the
API writes. The catalog is small at this point, so one pass in Python is fine.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from utils.translit import book_dedupe_key, detect_script

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_books() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT b.id, b.language, b.title, b.subtitle, p.name AS publisher,
                   coalesce(
                       array_agg(a.name ORDER BY ba.position) FILTER (WHERE a.id IS NOT NULL),
                       '{}'
                   ) AS authors
            FROM books b
            LEFT JOIN publishers p ON p.id = b.publisher_id
            LEFT JOIN book_authors ba ON ba.book_id = b.id
            LEFT JOIN authors a ON a.id = ba.author_id
            GROUP BY b.id, p.name
            """
        )
    ).mappings()
    update = sa.text("UPDATE books SET script = :script, dedupe_key = :key WHERE id = :id")
    for row in rows.all():
        script = detect_script(row["title"])
        key = book_dedupe_key(
            language=row["language"],
            script=script,
            title=row["title"],
            subtitle=row["subtitle"],
            authors=list(row["authors"]),
            publisher=row["publisher"],
        )
        conn.execute(update, {"script": script, "key": key, "id": row["id"]})


def upgrade() -> None:
    # --- users.max_stores ----------------------------------------------------
    op.add_column(
        "users", sa.Column("max_stores", sa.SmallInteger(), server_default=sa.text("1"), nullable=False)
    )
    op.create_check_constraint(op.f("ck_users_max_stores_range"), "users", "max_stores BETWEEN 0 AND 100")

    # --- tenants.launched_at -------------------------------------------------
    op.add_column("tenants", sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE tenants SET launched_at = created_at")

    # --- books ---------------------------------------------------------------
    op.add_column("books", sa.Column("script", sa.String(length=16), nullable=True))
    op.add_column("books", sa.Column("package_code", sa.String(length=20), nullable=True))
    op.add_column("books", sa.Column("review_note", sa.String(length=500), nullable=True))
    op.add_column("books", sa.Column("dedupe_key", sa.Text(), nullable=True))
    _backfill_books()
    op.alter_column("books", "script", nullable=False)
    op.alter_column("books", "dedupe_key", nullable=False)
    op.create_check_constraint(op.f("ck_books_book_script"), "books", "script IN ('latn', 'cyrl', 'other')")
    op.create_check_constraint(
        op.f("ck_books_package_code_format"), "books", "package_code ~ '^[0-9]{1,20}$'"
    )
    op.create_check_constraint(op.f("ck_books_dedupe_key_not_empty"), "books", "dedupe_key <> ''")
    op.create_index(
        "ix_books_dedupe_key", "books", ["dedupe_key"], postgresql_where=sa.text("status <> 'rejected'")
    )


def downgrade() -> None:
    op.drop_index("ix_books_dedupe_key", table_name="books")
    op.drop_constraint(op.f("ck_books_dedupe_key_not_empty"), "books", type_="check")
    op.drop_constraint(op.f("ck_books_package_code_format"), "books", type_="check")
    op.drop_constraint(op.f("ck_books_book_script"), "books", type_="check")
    op.drop_column("books", "dedupe_key")
    op.drop_column("books", "review_note")
    op.drop_column("books", "package_code")
    op.drop_column("books", "script")

    op.drop_column("tenants", "launched_at")

    op.drop_constraint(op.f("ck_users_max_stores_range"), "users", type_="check")
    op.drop_column("users", "max_stores")
