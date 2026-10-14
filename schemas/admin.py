"""
Platform admin schemas
======================
TenantAdminOut        a store in the admin's list: state, plan, owner, recent orders
TenantAdminDetailOut  one store: plus shelf, staff, bot and payment history
JobAdminOut           a background job (failed ones are retried by hand)
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from models.job import JobStatus
from models.tenant import Plan, TenantStatus
from schemas.base import ORMModel
from schemas.subscription import SubscriptionPaymentOut
from utils.plans import AccessState


class OwnerOut(BaseModel):
    user_id: int
    telegram_id: int
    first_name: str
    username: str | None
    phone: str | None


class TenantAdminOut(BaseModel):
    id: int
    slug: str
    name: str
    status: TenantStatus
    access: AccessState
    plan: Plan
    trial_ends_at: datetime | None
    paid_until: datetime | None
    suspended_reason: str | None
    launched_at: datetime | None
    created_at: datetime
    owner: OwnerOut | None
    orders_30d: int
    sales_30d: int  # tiyin, not cancelled
    last_order_at: datetime | None


class TenantAdminDetailOut(TenantAdminOut):
    items: int
    staff: int
    bot_username: str | None
    bot_group_linked: bool
    payments: list[SubscriptionPaymentOut]


class JobAdminOut(ORMModel):
    id: int
    kind: str
    tenant_id: int | None
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None
