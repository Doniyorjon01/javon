"""
Store statistics (owner)
========================
GET /tenants/{tenant_id}/stats?days=30   orders by status and channel, sales,
                                         average order, buyers (new / returning),
                                         sales per Tashkent day (zeros included,
                                         ready for a chart), the 10 best sellers,
                                         and the shelf (on sale, hidden, sold out)

Owner only: sales figures are the owner's business ("narx, sozlamalar va to'lov
faqat egasida"). The order badges staff need are GET .../orders/stats.
"""

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_owner
from database import db_stats
from database.config import get_pg_db
from schemas.stats import StoreStatsOut

router = APIRouter(prefix="/tenants/{tenant_id}/stats", tags=["stats"])


@router.get("", response_model=StoreStatsOut)
async def get_store_stats(
    days: int = Query(default=30, ge=1, le=366),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
) -> StoreStatsOut:
    return await db_stats.store_stats(db, owner.tenant_id, days)
