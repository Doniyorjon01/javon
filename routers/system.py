"""
Platform administration (sysadmin only)
=======================================
Same role as hik-backend's system.py: everything here needs
get_current_sysadmin (users.is_platform_admin).

GET   /system/catalog/books?status=pending        moderation queue, oldest first
PATCH /system/catalog/books/{book_id}             fix a book's data
POST  /system/catalog/books/{book_id}/approve     visible to every store from now on
POST  /system/catalog/books/{book_id}/reject      {"reason": ...}: hidden from every
                                                  store except the one that sent it,
                                                  which sees the reason; ISBN freed
PUT   /system/catalog/books/{book_id}/cover       multipart "file": set or replace a cover
DELETE /system/catalog/books/{book_id}/cover
GET   /system/users?telegram_id=...               accounts, newest first
PATCH /system/users/{user_id}                     limits, e.g. {"max_stores": 3}

Stores and subscriptions:
GET   /system/metrics                             the weekly numbers (stores, orders, revenue, queue)
GET   /system/tenants?q=&status=&closed=          stores, newest first: state, plan, owner, orders
GET   /system/tenants/{tenant_id}                 one store: plus shelf, staff, bot, payments
POST  /system/tenants/{tenant_id}/suspend         {"reason": ...}: storefront hidden, panel read-only
POST  /system/tenants/{tenant_id}/activate        undo a suspension
POST  /system/tenants/{tenant_id}/subscription/payments
                                                  record a payment {"plan", "months", "amount"?, "note"?}:
                                                  extends paid_until, sets the plan, reopens the store;
                                                  the owner gets a Telegram message
GET   /system/tenants/{tenant_id}/subscription/payments   history, voided ones included
POST  /system/subscription-payments/{payment_id}/void     a mistaken payment; paid_until recomputed
PATCH /system/tenants/{tenant_id}/subscription    manual fix: plan, trial_ends_at, paid_until

Background jobs:
GET   /system/jobs?status=failed&kind=            newest first
POST  /system/jobs/{job_id}/retry                 a failed job back to the queue
"""

from fastapi import APIRouter, Depends, File, Path, Query, Security, UploadFile, status
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import get_current_sysadmin
from config import settings
from database import db_admin, db_catalog, db_subscription, db_tenant, db_user
from database.config import get_pg_db
from database.db_job import JobKind
from models.catalog import Book, BookStatus
from models.job import JobStatus
from models.subscription import SubscriptionPayment
from models.tenant import TenantStatus
from models.user import User
from schemas.admin import JobAdminOut, TenantAdminDetailOut, TenantAdminOut
from schemas.base import BIGINT_MAX
from schemas.catalog import BookOut, BookUpdate, RejectIn
from schemas.stats import PlatformMetricsOut
from schemas.subscription import SubscriptionPaymentIn, SubscriptionPaymentOut, SubscriptionUpdate, SuspendIn
from schemas.user import UserAdminOut, UserAdminUpdate
from services.media import read_upload
from services.storage import Storage, get_storage
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
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.update_book(db, book_id, data, lang)


@router.post("/catalog/books/{book_id}/approve", response_model=BookOut)
async def approve_book(
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.set_book_status(db, book_id, BookStatus.APPROVED, lang)


@router.post("/catalog/books/{book_id}/reject", response_model=BookOut)
async def reject_book(
    data: RejectIn,
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.set_book_status(db, book_id, BookStatus.REJECTED, lang, note=data.reason)


@router.put("/catalog/books/{book_id}/cover", response_model=BookOut)
async def upload_cover(
    file: UploadFile = File(description="JPEG, PNG or WebP"),
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_storage),
    lang: Lang = Depends(get_lang),
) -> Book:
    data = await read_upload(file, settings.MAX_UPLOAD_BYTES, lang)
    return await db_catalog.set_cover(db, storage, book_id, data, lang, tenant_id=None)


@router.delete("/catalog/books/{book_id}/cover", response_model=BookOut)
async def delete_cover(
    book_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    storage: Storage = Depends(get_storage),
    lang: Lang = Depends(get_lang),
) -> Book:
    return await db_catalog.delete_cover(db, storage, book_id, lang)


@router.get("/users", response_model=CustomPage[UserAdminOut])
async def get_users(
    telegram_id: int | None = Query(default=None, gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_user.get_users(telegram_id))


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    data: UserAdminUpdate,
    user_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> User:
    return await db_user.update_user_limits(db, user_id, data, lang)


# --------------------------------------------------------------------------- #
# Stores and subscriptions
# --------------------------------------------------------------------------- #
TenantId = Path(gt=0, le=BIGINT_MAX)


@router.get("/metrics", response_model=PlatformMetricsOut)
async def get_metrics(
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> PlatformMetricsOut:
    return await db_admin.platform_metrics(db)


@router.get("/tenants", response_model=CustomPage[TenantAdminOut])
async def get_tenants(
    q: str | None = Query(default=None, max_length=80, description="Name or slug"),
    tenant_status: TenantStatus | None = Query(default=None, alias="status"),
    closed: bool | None = Query(default=None, description="true: expired or suspended"),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    stmt, transformer = db_admin.get_tenants(q, tenant_status, closed)
    return await apaginate(db, stmt, transformer=transformer)


@router.get("/tenants/{tenant_id}", response_model=TenantAdminDetailOut)
async def get_tenant(
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> TenantAdminDetailOut:
    return await db_admin.get_tenant_detail(db, tenant_id, lang)


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantAdminDetailOut)
async def suspend_tenant(
    data: SuspendIn,
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> TenantAdminDetailOut:
    await db_tenant.set_suspended(db, tenant_id, data.reason, lang, notify=True)
    return await db_admin.get_tenant_detail(db, tenant_id, lang)


@router.post("/tenants/{tenant_id}/activate", response_model=TenantAdminDetailOut)
async def activate_tenant(
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> TenantAdminDetailOut:
    await db_tenant.set_suspended(db, tenant_id, None, lang)
    return await db_admin.get_tenant_detail(db, tenant_id, lang)


@router.post(
    "/tenants/{tenant_id}/subscription/payments",
    response_model=SubscriptionPaymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_payment(
    data: SubscriptionPaymentIn,
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> SubscriptionPayment:
    return await db_subscription.record_payment(db, tenant_id, data, admin.id, lang)


@router.get("/tenants/{tenant_id}/subscription/payments", response_model=CustomPage[SubscriptionPaymentOut])
async def get_payments(
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_subscription.get_payments(tenant_id))


@router.post("/subscription-payments/{payment_id}/void", response_model=SubscriptionPaymentOut)
async def void_payment(
    payment_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> SubscriptionPayment:
    return await db_subscription.void_payment(db, payment_id, lang)


@router.patch("/tenants/{tenant_id}/subscription", response_model=TenantAdminDetailOut)
async def update_subscription(
    data: SubscriptionUpdate,
    tenant_id: int = TenantId,
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> TenantAdminDetailOut:
    await db_subscription.update_subscription(db, tenant_id, data, lang)
    return await db_admin.get_tenant_detail(db, tenant_id, lang)


# --------------------------------------------------------------------------- #
# Background jobs
# --------------------------------------------------------------------------- #
@router.get("/jobs", response_model=CustomPage[JobAdminOut])
async def get_jobs(
    job_status: JobStatus | None = Query(default=None, alias="status"),
    kind: JobKind | None = Query(default=None),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
) -> object:
    return await apaginate(db, db_admin.get_jobs(job_status, kind))


@router.post("/jobs/{job_id}/retry", response_model=JobAdminOut)
async def retry_job(
    job_id: int = Path(gt=0, le=BIGINT_MAX),
    admin: User = Security(get_current_sysadmin),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> JobAdminOut:
    return await db_admin.retry_job(db, job_id, lang)
