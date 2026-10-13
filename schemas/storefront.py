"""
Storefront schemas — what buyers see
====================================
Only what a buyer needs: no moderation status, no stock numbers (just
in_stock), no internal ids beyond the book id used in page URLs
(/kitob/{book_id}). Prices in tiyin; the frontend formats so'm.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from models.catalog import BookLanguage, BookScript
from schemas.base import ORMModel
from schemas.catalog import AuthorOut, PublisherOut
from services.media import image_urls
from utils.images import COVER_SPEC


class StorefrontSort(StrEnum):
    RELEVANCE = "relevance"  # best match first; the default with a search query
    NEW = "new"  # recently added to the shelf; the default without one
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    TITLE = "title"


class BookCard(ORMModel):
    id: int
    title: str
    subtitle: str | None
    authors: list[AuthorOut]
    publisher: PublisherOut | None
    language: BookLanguage
    script: BookScript
    cover_key: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cover(self) -> dict[str, str] | None:
        return image_urls(self.cover_key, COVER_SPEC)


class BookPage(BookCard):
    isbn13: str | None
    published_year: int | None
    pages: int | None
    description: str | None


class StorefrontItemOut(ORMModel):
    book: BookCard
    price: int
    quantity: int = Field(exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_stock(self) -> bool:
        return self.quantity > 0


class StorefrontItemPageOut(StorefrontItemOut):
    book: BookPage
    # Same author first, then same publisher; in-stock books first. At most 8.
    similar: list[StorefrontItemOut] = Field(default_factory=list)


class FacetValue(BaseModel):
    value: str
    count: int


class FacetEntity(BaseModel):
    id: int
    name: str
    count: int


class FacetsOut(BaseModel):
    """What the filter panel can offer for this store's shelf."""

    total: int
    languages: list[FacetValue]
    scripts: list[FacetValue]
    authors: list[FacetEntity]  # the most frequent, at most FACET_LIMIT
    publishers: list[FacetEntity]
    price_min: int | None
    price_max: int | None


class SitemapEntry(BaseModel):
    book_id: int
    updated_at: datetime
