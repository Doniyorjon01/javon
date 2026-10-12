"""
Platform administration (sysadmin only)
=======================================
Same role as hik-backend's system.py: everything here needs
get_current_sysadmin (users.is_platform_admin).

GET   /system/catalog/books?status=pending        moderation queue, oldest first
PATCH /system/catalog/books/{book_id}             fix a book's data
POST  /system/catalog/books/{book_id}/approve     visible to every store from now on
POST  /system/catalog/books/{book_id}/reject      hidden from everyone; ISBN freed
"""

from fastapi import APIRouter, Depends, Path, Query, Security
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import get_current_sysadmin
from database import db_catalog
from database.config import get_pg_db
from models.catalog import Book, BookStatus
from models.user import User
from schemas.catalog import BookOut, BookUpdate
from utils.i18n import Lang, get_lang
from utils.pagination import CustomPage

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/catalog/books", response_model=CustomPage[BookOut])
async def get_books_for_review(
    book_status: BookStatus = Query(default=BookStatus.PENDING, alias="status"),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_catalog.get_books_for_review(book_status))


@router.patch("/catalog/books/{book_id}", response_model=BookOut)
async def update_book(
    data: BookUpdate,
    book_id: int = Path(gt=0),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.update_book(db, book_id, data, lang)


@router.post("/catalog/books/{book_id}/approve", response_model=BookOut)
async def approve_book(
    book_id: int = Path(gt=0),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.set_book_status(db, book_id, BookStatus.APPROVED, lang)


@router.post("/catalog/books/{book_id}/reject", response_model=BookOut)
async def reject_book(
    book_id: int = Path(gt=0),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.set_book_status(db, book_id, BookStatus.REJECTED, lang)
