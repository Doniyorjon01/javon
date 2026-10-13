"""
Order notifications
===================
Jobs written by db_order in the same transaction as the order (the outbox).
Delivery to the store's Telegram group and to the buyer comes with the Telegram
bot step; until then the job only records that it ran, so the whole path
(order -> job -> worker) already works and is tested.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.job import Job

logger = logging.getLogger(__name__)


async def order_created(db: AsyncSession, job: Job) -> None:
    logger.info(
        "Order created; Telegram delivery not connected yet",
        extra={"tenant_id": job.tenant_id, "order_id": job.payload.get("order_id")},
    )


async def order_status_changed(db: AsyncSession, job: Job) -> None:
    logger.info(
        "Order status changed; Telegram delivery not connected yet",
        extra={
            "tenant_id": job.tenant_id,
            "order_id": job.payload.get("order_id"),
            "status": job.payload.get("status"),
        },
    )
