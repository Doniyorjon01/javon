"""
Catalog — the store's side
==========================
Used from the admin panel while adding books to the store's shelf.

GET  /tenants/{tenant_id}/catalog/books?q=...   search (title, author, publisher, ISBN)
GET  /tenants/{tenant_id}/catalog/isbn/{isbn}   barcode scanner: exact ISBN lookup;
                                                404 book_isbn_not_found = offer "add it"
GET  /tenants/{tenant_id}/catalog/books/{id}    one book
POST /tenants/{tenant_id}/catalog/books         add a book that is not in the catalog;
                                                it is "pending" until a platform admin
                                                approves it, but this store can use it now.
                                                409 book_duplicate carries "book_id": the
                                                same ISBN-less book exists, use that one.
                                                409 pending_books_limit: too many books
                                                are waiting for moderation
GET  /tenants/{tenant_id}/catalog/submissions?status=...
                                                books this store added and what became of
                                                them; rejected ones carry review_note

Any member of the store (owner or staff) may do all of this.
"""

from fastapi import APIRouter, Depends, Path, Query, Security, status
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member
from database import db_catalog
from database.config import get_pg_db
from models.catalog import Book, BookStatus
from schemas.base import BIGINT_MAX
from schemas.catalog import BookCreate, BookOut
from utils.i18n import Lang, get_lang
from utils.pagination import CustomPage

router = APIRouter(prefix="/tenants/{tenant_id}/catalog", tags=["catalog"])


@router.get("/books", response_model=CustomPage[BookOut])
async def search_books(
    q: str = Query(min_length=1, max_length=100, description="Title, author, publisher or ISBN"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> object:
    return await apaginate(db, db_catalog.search_books(member.tenant_id, q, lang))


@router.get("/isbn/{isbn}", response_model=BookOut)
async def get_book_by_isbn(
    isbn: str = Path(min_length=10, max_length=20),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.get_book_by_isbn(db, member.tenant_id, isbn, lang)


@router.get("/books/{book_id}", response_model=BookOut)
async def get_book(
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.get_book(db, member.tenant_id, book_id, lang)


@router.post("/books", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_book(
    data: BookCreate,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.create_book(db, data, tenant_id=member.tenant_id, lang=lang)


@router.get("/submissions", response_model=CustomPage[BookOut])
async def get_submissions(
    book_status: BookStatus | None = Query(default=None, alias="status"),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_catalog.get_submissions(member.tenant_id, book_status))
