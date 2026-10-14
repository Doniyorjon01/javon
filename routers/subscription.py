"""
Plans and the store's subscription
==================================
GET /plans                            public: prices and limits for the pricing page
GET /tenants/{tenant_id}/subscription owner: plan, state (trial / active / grace /
                                      expired / suspended), dates, usage against the
                                      plan's limits, where to pay, payment history

Owners pay by card transfer to the platform (PLATFORM_CARD_NUMBER); the platform
admin records the payment (routers/system.py). After the paid period or the trial
ends the store works SUBSCRIPTION_GRACE_DAYS more, then its storefront is hidden
and its admin panel is read-only (403 subscription_expired on every write) until
a payment is recorded. The frontend shows a banner from `state` and `closes_at`;
GET /auth/me also carries each store's `access` state.
"""

from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_owner
from config import settings
from database import db_subscription
from database.config import get_pg_db
from schemas.subscription import PlansOut, SubscriptionOut, all_plans
from utils.i18n import Lang, get_lang

router = APIRouter(tags=["subscription"])


@router.get("/plans", response_model=PlansOut)
async def get_plans() -> PlansOut:
    return PlansOut(trial_days=settings.TRIAL_DAYS, plans=all_plans())


@router.get("/tenants/{tenant_id}/subscription", response_model=SubscriptionOut)
async def get_subscription(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> SubscriptionOut:
    return await db_subscription.get_subscription(db, owner.tenant_id, lang)
