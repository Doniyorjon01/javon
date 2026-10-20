"""
Book catalog
============
ONE shared catalog for the whole platform: a book is described once and every
store that sells it points at the same row. Prices and stock are per store and
live in the store's inventory (step 6), never here.

Platform-level tables: no tenant_id, no RLS. Visibility is explicit instead:
  * approved  — seen by every store;
  * pending   — added by a store, waiting for moderation; only that store sees it
                (created_by_tenant_id) and may already sell it;
  * rejected  — hidden from everyone; its ISBN becomes free again.

search_text is the normalized "title subtitle authors publisher isbn" string
(utils/translit.search_key) with a trigram index: Latin and Cyrillic queries,
partial words and small typos all find the book.

dedupe_key catches the same ISBN-less book being added twice: language, script,
title, authors and publisher, normalized. `script` is part of it because the
Latin and Cyrillic editions of a book are different products even though their
search_text is the same.

Both are written only by database/db_catalog.py, which recomputes them whenever
any of their parts change.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, BaseModel
from models.tenant import enum_check, str_enum

if TYPE_CHECKING:
    from models.tenant import Tenant


class BookStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BookScript(StrEnum):
    """The alphabet the book is printed in (ISO 15924 codes)."""

    LATN = "latn"
    CYRL = "cyrl"
    OTHER = "other"  # no letters to judge by ("1984") or another alphabet


class BookSource(StrEnum):
    """How a store submitted the book; NULL for books loaded by the platform.
    Pending books are limited per source (settings.MAX_PENDING_BOOKS_*)."""

    MANUAL = "manual"  # one by one in the admin panel
    IMPORT = "import"  # from the store's Excel file


class BookLanguage(StrEnum):
    UZ = "uz"  # O'zbekcha (lotin yoki kirill)
    RU = "ru"
    EN = "en"
    OTHER = "other"


NAME_MAX_LENGTH = 160
TITLE_MAX_LENGTH = 300
DESCRIPTION_MAX_LENGTH = 5000
MAX_AUTHORS = 10
REVIEW_NOTE_MAX_LENGTH = 500
PACKAGE_CODE_PATTERN = r"^[0-9]{1,20}$"


class Author(BaseModel):
    """
    One row per spelling ALPHABET: "Abdulla Qodiriy" (latn) and "Абдулла Қодирий"
    (cyrl) are two rows with the same search_key, so a Cyrillic edition shows its
    author in Cyrillic, and a search for either spelling finds both.
    """

    __tablename__ = "authors"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    search_key: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH * 2))
    script: Mapped[BookScript] = mapped_column(str_enum(BookScript), server_default=BookScript.LATN.value)

    __table_args__ = (
        CheckConstraint("search_key <> ''", name="search_key_not_empty"),
        enum_check("script", BookScript, "author_script"),
        UniqueConstraint("search_key", "script", name="uq_authors_search_key_script"),
    )


class Publisher(BaseModel):
    """Like Author: one row per alphabet ("Sharq" and "Шарқ")."""

    __tablename__ = "publishers"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    search_key: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH * 2))
    script: Mapped[BookScript] = mapped_column(str_enum(BookScript), server_default=BookScript.LATN.value)

    __table_args__ = (
        CheckConstraint("search_key <> ''", name="search_key_not_empty"),
        enum_check("script", BookScript, "publisher_script"),
        UniqueConstraint("search_key", "script", name="uq_publishers_search_key_script"),
    )


class BookAuthor(Base):
    """Plain link table; `position` keeps the order printed on the cover."""

    __tablename__ = "book_authors"

    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authors.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)

    __table_args__ = (CheckConstraint("position >= 0", name="position_not_negative"),)


class Book(BaseModel):
    __tablename__ = "books"

    isbn13: Mapped[str | None] = mapped_column(String(13))
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    subtitle: Mapped[str | None] = mapped_column(String(TITLE_MAX_LENGTH))
    publisher_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("publishers.id", ondelete="RESTRICT"), index=True
    )
    language: Mapped[BookLanguage] = mapped_column(
        str_enum(BookLanguage), server_default=BookLanguage.UZ.value
    )
    script: Mapped[BookScript] = mapped_column(str_enum(BookScript))
    published_year: Mapped[int | None] = mapped_column(SmallInteger)
    pages: Mapped[int | None] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(Text)
    cover_key: Mapped[str | None] = mapped_column(String(255))  # file storage key, not a URL
    # MXIK (IKPU): 17-digit product code from tasnif.soliq.uz, needed for fiscal receipts.
    mxik_code: Mapped[str | None] = mapped_column(String(17))
    # Package (unit) code that goes with the MXIK code on a fiscal receipt.
    package_code: Mapped[str | None] = mapped_column(String(20))

    status: Mapped[BookStatus] = mapped_column(str_enum(BookStatus), server_default=BookStatus.PENDING.value)
    # The store that added the book; NULL for books loaded by the platform.
    created_by_tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    submitted_via: Mapped[BookSource | None] = mapped_column(str_enum(BookSource))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why the moderator rejected the book; shown to the store that submitted it.
    review_note: Mapped[str | None] = mapped_column(String(REVIEW_NOTE_MAX_LENGTH))

    search_text: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)

    authors: Mapped[list[Author]] = relationship(
        secondary="book_authors",
        order_by="BookAuthor.position",
        viewonly=True,
        lazy="raise",
    )
    publisher: Mapped[Publisher | None] = relationship(lazy="raise")
    created_by_tenant: Mapped["Tenant | None"] = relationship(lazy="raise")

    __table_args__ = (
        enum_check("status", BookStatus, "book_status"),
        enum_check("language", BookLanguage, "book_language"),
        enum_check("script", BookScript, "book_script"),
        enum_check("submitted_via", BookSource, "book_submitted_via"),
        CheckConstraint(
            "(created_by_tenant_id IS NULL) = (submitted_via IS NULL)", name="submitted_via_with_tenant"
        ),
        CheckConstraint("isbn13 ~ '^97[89][0-9]{10}$'", name="isbn13_format"),
        CheckConstraint("char_length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("published_year BETWEEN 1450 AND 2100", name="published_year_range"),
        CheckConstraint("pages BETWEEN 1 AND 20000", name="pages_range"),
        CheckConstraint(f"char_length(description) <= {DESCRIPTION_MAX_LENGTH}", name="description_length"),
        CheckConstraint("mxik_code ~ '^[0-9]{17}$'", name="mxik_code_format"),
        CheckConstraint(f"package_code ~ '{PACKAGE_CODE_PATTERN}'", name="package_code_format"),
        CheckConstraint("search_text <> ''", name="search_text_not_empty"),
        CheckConstraint("dedupe_key <> ''", name="dedupe_key_not_empty"),
        # One live record per ISBN; a rejected record frees its ISBN.
        Index(
            "uq_books_isbn13_live",
            "isbn13",
            unique=True,
            postgresql_where=text("isbn13 IS NOT NULL AND status <> 'rejected'"),
        ),
        # Latin/Cyrillic/typo-tolerant search (pg_trgm).
        Index(
            "ix_books_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        # "Is this ISBN-less book already in the catalog?" (db_catalog.create_book).
        Index("ix_books_dedupe_key", "dedupe_key", postgresql_where=text("status <> 'rejected'")),
        # The moderation queue and "my store's pending books".
        Index(
            "ix_books_pending",
            "created_by_tenant_id",
            "submitted_via",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
