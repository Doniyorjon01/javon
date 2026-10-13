"""
Inventory — the store's shelf
=============================
Prices are in tiyin. Owner and staff work here; price, visibility, adding and
removing books, and imports are the owner's (plan: "narx, sozlamalar va to'lov
faqat egasida").

GET    /tenants/{tenant_id}/inventory?q=&in_stock=&visible=&sort=   the shelf
GET    /tenants/{tenant_id}/inventory/isbn/{isbn}       scanner: is it on our shelf?
GET    /tenants/{tenant_id}/inventory/{item_id}
POST   /tenants/{tenant_id}/inventory                   owner: put a catalog book on sale;
                                                        409 inventory_item_exists + item_id
PATCH  /tenants/{tenant_id}/inventory/{item_id}         price, is_visible (owner); quantity
POST   /tenants/{tenant_id}/inventory/{item_id}/adjust  {"delta": +5}: stock arrived / sold
                                                        in the shop; never below zero
DELETE /tenants/{tenant_id}/inventory/{item_id}         owner: off the shelf

GET    /tenants/{tenant_id}/inventory/import-template   the .xlsx to fill in
POST   /tenants/{tenant_id}/inventory/imports           owner, multipart "file": 202, the
                                                        worker processes it; poll the import
GET    /tenants/{tenant_id}/inventory/imports           owner: past imports
GET    /tenants/{tenant_id}/inventory/imports/{id}      owner: status, counters, error lines

Static paths are declared before /{item_id}: FastAPI matches in order.
"""

import asyncio

from fastapi import APIRouter, Depends, File, Path, Query, Response, Security, UploadFile, status
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member, get_current_owner
from config import settings
from database import db_inventory
from database.config import get_pg_db
from models.inventory import InventoryImport, InventoryItem
from schemas.base import BIGINT_MAX
from schemas.inventory import (
    InventoryImportOut,
    InventoryItemCreate,
    InventoryItemOut,
    InventoryItemUpdate,
    InventorySort,
    StockAdjustIn,
)
from services.excel import build_template
from services.media import read_upload
from utils.i18n import Lang, get_lang
from utils.pagination import CustomPage

router = APIRouter(prefix="/tenants/{tenant_id}/inventory", tags=["inventory"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ItemId = Path(gt=0, le=BIGINT_MAX)


@router.get("", response_model=CustomPage[InventoryItemOut])
async def get_items(
    q: str | None = Query(default=None, max_length=100, description="Title, author, publisher or ISBN"),
    in_stock: bool | None = None,
    visible: bool | None = None,
    sort: InventorySort = InventorySort.UPDATED,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    stmt = db_inventory.get_items(member.tenant_id, query=q, in_stock=in_stock, visible=visible, sort=sort)
    return await apaginate(db, stmt)


@router.get("/import-template")
async def get_import_template(member: CurrentMember = Security(get_current_member)) -> Response:
    content = await asyncio.to_thread(build_template)
    return Response(
        content=content,
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="javon-kitoblar.xlsx"'},
    )


@router.post("/imports", response_model=InventoryImportOut, status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    file: UploadFile = File(description=".xlsx made from the template"),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryImport:
    data = await read_upload(file, settings.MAX_UPLOAD_BYTES, lang)
    return await db_inventory.create_import(
        db, owner.tenant_id, owner.user.id, file.filename or "import.xlsx", data, lang
    )


@router.get("/imports", response_model=CustomPage[InventoryImportOut])
async def get_imports(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_inventory.get_imports(owner.tenant_id))


@router.get("/imports/{import_id}", response_model=InventoryImportOut)
async def get_import(
    import_id: int = Path(gt=0, le=BIGINT_MAX),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryImport:
    return await db_inventory.get_import(db, owner.tenant_id, import_id, lang)


@router.get("/isbn/{isbn}", response_model=InventoryItemOut)
async def get_item_by_isbn(
    isbn: str = Path(min_length=10, max_length=20),
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryItem:
    return await db_inventory.get_item_by_isbn(db, member.tenant_id, isbn, lang)


@router.post("", response_model=InventoryItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    data: InventoryItemCreate,
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryItem:
    return await db_inventory.create_item(db, owner.tenant_id, data, lang)


@router.get("/{item_id}", response_model=InventoryItemOut)
async def get_item(
    item_id: int = ItemId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryItem:
    return await db_inventory.get_item(db, member.tenant_id, item_id, lang)


@router.patch("/{item_id}", response_model=InventoryItemOut)
async def update_item(
    data: InventoryItemUpdate,
    item_id: int = ItemId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryItem:
    return await db_inventory.update_item(db, member.tenant_id, item_id, data, member.role, lang)


@router.post("/{item_id}/adjust", response_model=InventoryItemOut)
async def adjust_quantity(
    data: StockAdjustIn,
    item_id: int = ItemId,
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InventoryItem:
    return await db_inventory.adjust_quantity(db, member.tenant_id, item_id, data.delta, lang)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int = ItemId,
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> None:
    await db_inventory.delete_item(db, owner.tenant_id, item_id, lang)
