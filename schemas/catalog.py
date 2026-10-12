"""
Catalog schemas
===============
BookCreate  a store adds a book that is not in the catalog yet. Status and the
            submitting store are set by the server (mass-assignment guard:
            extra="forbid").
BookUpdate  a platform admin corrects a book during moderation. Every field is
            optional; apply with model_dump(exclude_unset=True).
BookOut     what the admin panel shows. `isbn` accepts ISBN-10 or ISBN-13 with
            or without hyphens; it is always returned as plain ISBN-13 digits.
RejectIn    the moderator's reason, shown to the store that submitted the book.

`script` (Latin / Cyrillic edition) may be left out: the server then detects it
from the title.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from models.catalog import (
    DESCRIPTION_MAX_LENGTH,
    MAX_AUTHORS,
    NAME_MAX_LENGTH,
    PACKAGE_CODE_PATTERN,
    REVIEW_NOTE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    BookLanguage,
    BookScript,
    BookStatus,
)
from schemas.base import ORMModel
from utils.isbn import normalize_isbn
from utils.translit import search_key


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _valid_isbn(value: str) -> str:
    isbn13 = normalize_isbn(value)
    if isbn13 is None:
        raise ValueError("not a valid ISBN-10 or ISBN-13 (check the digits)")
    return isbn13


def _searchable(value: str) -> str:
    if not search_key(value):
        raise ValueError("must contain letters or digits")
    return value


def _unique_names(names: list[str]) -> list[str]:
    keys = [search_key(name) for name in names]
    if len(set(keys)) != len(keys):
        raise ValueError("the same author is listed twice")
    return names


Isbn = Annotated[str, AfterValidator(_valid_isbn)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH)]
Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH),
    AfterValidator(_searchable),
]
AuthorNames = Annotated[
    list[Name], Field(min_length=1, max_length=MAX_AUTHORS), AfterValidator(_unique_names)
]
Year = Annotated[int, Field(ge=1450, le=2100)]
Pages = Annotated[int, Field(ge=1, le=20000)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=DESCRIPTION_MAX_LENGTH)]
MxikCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{17}$")]
PackageCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PACKAGE_CODE_PATTERN)]


class BookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isbn: Annotated[Isbn | None, BeforeValidator(_empty_to_none)] = None
    title: Title
    subtitle: Annotated[Title | None, BeforeValidator(_empty_to_none)] = None
    authors: AuthorNames
    publisher: Annotated[Name | None, BeforeValidator(_empty_to_none)] = None
    language: BookLanguage = BookLanguage.UZ
    script: BookScript | None = None  # None: detected from the title
    published_year: Year | None = None
    pages: Pages | None = None
    description: Annotated[Description | None, BeforeValidator(_empty_to_none)] = None
    mxik_code: Annotated[MxikCode | None, BeforeValidator(_empty_to_none)] = None
    package_code: Annotated[PackageCode | None, BeforeValidator(_empty_to_none)] = None


class BookUpdate(BaseModel):
    """Empty string clears an optional field. `title`, `authors`, `language` and
    `script` cannot be cleared, only replaced."""

    model_config = ConfigDict(extra="forbid")

    isbn: Annotated[Isbn | None, BeforeValidator(_empty_to_none)] = None
    title: Title | None = None
    subtitle: Annotated[Title | None, BeforeValidator(_empty_to_none)] = None
    authors: AuthorNames | None = None
    publisher: Annotated[Name | None, BeforeValidator(_empty_to_none)] = None
    language: BookLanguage | None = None
    script: BookScript | None = None
    published_year: Year | None = None
    pages: Pages | None = None
    description: Annotated[Description | None, BeforeValidator(_empty_to_none)] = None
    mxik_code: Annotated[MxikCode | None, BeforeValidator(_empty_to_none)] = None
    package_code: Annotated[PackageCode | None, BeforeValidator(_empty_to_none)] = None


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=REVIEW_NOTE_MAX_LENGTH)
    ]


class AuthorOut(ORMModel):
    id: int
    name: str


class PublisherOut(ORMModel):
    id: int
    name: str


class BookOut(ORMModel):
    id: int
    isbn13: str | None
    title: str
    subtitle: str | None
    authors: list[AuthorOut]
    publisher: PublisherOut | None
    language: BookLanguage
    script: BookScript
    published_year: int | None
    pages: int | None
    description: str | None
    mxik_code: str | None
    package_code: str | None
    status: BookStatus
    review_note: str | None  # set when rejected: why
    created_at: datetime
