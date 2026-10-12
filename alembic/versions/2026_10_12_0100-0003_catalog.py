"""catalog: authors, publishers, books, book_authors

Revision ID: 0003
Revises: 39852fd53b87
Create Date: 2026-10-12 01:00:00+05:00

Shared, platform-level catalog (no RLS; visibility is filtered explicitly, see
models/catalog.py). Needs pg_trgm for Latin/Cyrillic/typo-tolerant search:
pg_trgm is a "trusted" extension, so the database owner (javon_owner) may create
it without superuser rights.

Also closes a gap from the first migration: the API role may read which
migration is applied, never change it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "39852fd53b87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    """models/base.py BaseModel columns."""
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM javon_app")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for table in ("authors", "publishers"):
        op.create_table(
            table,
            *_base_columns(),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("search_key", sa.String(length=320), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint("search_key", name=op.f(f"uq_{table}_search_key")),
            sa.CheckConstraint("search_key <> ''", name=op.f(f"ck_{table}_search_key_not_empty")),
        )

    op.create_table(
        "books",
        *_base_columns(),
        sa.Column("isbn13", sa.String(length=13), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("subtitle", sa.String(length=300), nullable=True),
        sa.Column("publisher_id", sa.BigInteger(), nullable=True),
        sa.Column("language", sa.String(length=16), server_default="uz", nullable=False),
        sa.Column("published_year", sa.SmallInteger(), nullable=True),
        sa.Column("pages", sa.SmallInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_key", sa.String(length=255), nullable=True),
        sa.Column("mxik_code", sa.String(length=17), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_by_tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_books")),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["publishers.id"],
            name=op.f("fk_books_publisher_id_publishers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_tenant_id"],
            ["tenants.id"],
            name=op.f("fk_books_created_by_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name=op.f("ck_books_book_status")
        ),
        sa.CheckConstraint("language IN ('uz', 'ru', 'en', 'other')", name=op.f("ck_books_book_language")),
        sa.CheckConstraint("isbn13 ~ '^97[89][0-9]{10}$'", name=op.f("ck_books_isbn13_format")),
        sa.CheckConstraint("char_length(btrim(title)) > 0", name=op.f("ck_books_title_not_blank")),
        sa.CheckConstraint(
            "published_year BETWEEN 1450 AND 2100", name=op.f("ck_books_published_year_range")
        ),
        sa.CheckConstraint("pages BETWEEN 1 AND 20000", name=op.f("ck_books_pages_range")),
        sa.CheckConstraint("char_length(description) <= 5000", name=op.f("ck_books_description_length")),
        sa.CheckConstraint("mxik_code ~ '^[0-9]{17}$'", name=op.f("ck_books_mxik_code_format")),
        sa.CheckConstraint("search_text <> ''", name=op.f("ck_books_search_text_not_empty")),
    )
    op.create_index(op.f("ix_books_publisher_id"), "books", ["publisher_id"])
    # One live record per ISBN; a rejected record frees its ISBN.
    op.create_index(
        "uq_books_isbn13_live",
        "books",
        ["isbn13"],
        unique=True,
        postgresql_where=sa.text("isbn13 IS NOT NULL AND status <> 'rejected'"),
    )
    op.create_index(
        "ix_books_search_text_trgm",
        "books",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_books_pending",
        "books",
        ["created_by_tenant_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "book_authors",
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("book_id", "author_id", name=op.f("pk_book_authors")),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_book_authors_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["authors.id"], name=op.f("fk_book_authors_author_id_authors"), ondelete="RESTRICT"
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_book_authors_position_not_negative")),
    )
    op.create_index(op.f("ix_book_authors_author_id"), "book_authors", ["author_id"])


def downgrade() -> None:
    op.drop_table("book_authors")
    op.drop_table("books")
    op.drop_table("publishers")
    op.drop_table("authors")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
