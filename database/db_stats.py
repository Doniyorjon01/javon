"""
Store statistics — database layer
=================================
The owner's dashboard: a handful of aggregate queries over the store's orders
(the session is bound to the store, so RLS applies) for the last `days` days,
counted in Tashkent calendar days. Cancelled orders count in by_status only;
"sales" means orders that were not cancelled, "completed_sales" the delivered ones.

Every query is an aggregate over the index ix_orders_tenant_status_created
(tenant_id, status, created_at); nothing is loaded row by row.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.inventory import InventoryItem
from models.order import Order, OrderChannel, OrderItem, OrderStatus
from schemas.stats import DayStatsOut, InventoryStatsOut, StoreStatsOut, TopBookOut

TASHKENT = ZoneInfo("Asia/Tashkent")
TOP_BOOKS = 10


def period_start(days: int, now: datetime) -> tuple[date, datetime]:
    """First Tashkent day of the period and the moment it began (UTC)."""
    first_day = now.astimezone(TASHKENT).date() - timedelta(days=days - 1)
    return first_day, datetime.combine(first_day, time.min, tzinfo=TASHKENT).astimezone(UTC)


async def store_stats(db: AsyncSession, tenant_id: int, days: int) -> StoreStatsOut:
    first_day, since = period_start(days, datetime.now(UTC))
    in_period = (Order.tenant_id == tenant_id, Order.created_at >= since)
    kept = Order.status != OrderStatus.CANCELLED

    by_status = {
        row.status: row.count
        for row in await db.execute(
            select(Order.status, func.count().label("count")).where(*in_period).group_by(Order.status)
        )
    }
    by_channel = {
        row.channel: row.count
        for row in await db.execute(
            select(Order.channel, func.count().label("count")).where(*in_period).group_by(Order.channel)
        )
    }
    totals = (
        await db.execute(
            select(
                func.count().filter(kept).label("kept"),
                func.coalesce(func.sum(Order.total).filter(kept), 0).label("sales"),
                func.coalesce(func.sum(Order.total).filter(Order.status == OrderStatus.COMPLETED), 0).label(
                    "completed"
                ),
            ).where(*in_period)
        )
    ).one()

    local_day = cast(func.timezone("Asia/Tashkent", Order.created_at), Date).label("day")
    day_rows = {
        row.day: row
        for row in await db.execute(
            select(
                local_day,
                func.count().label("orders"),
                func.coalesce(func.sum(Order.total), 0).label("sales"),
            )
            .where(*in_period, kept)
            .group_by(local_day)
        )
    }
    by_day = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        row = day_rows.get(day)
        by_day.append(DayStatsOut(day=day, orders=row.orders if row else 0, sales=row.sales if row else 0))

    top = await db.execute(
        select(
            OrderItem.book_id,
            func.max(OrderItem.title).label("title"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(OrderItem.line_total).label("sales"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.tenant_id == tenant_id, *in_period, kept)
        .group_by(OrderItem.book_id)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.book_id)
        .limit(TOP_BOOKS)
    )

    per_customer = (
        select(Order.customer_id, func.count().label("n")).where(*in_period, kept).group_by(Order.customer_id)
    ).subquery()
    customers = (
        await db.execute(
            select(func.count().label("all"), func.count().filter(per_customer.c.n > 1).label("returning"))
        )
    ).one()

    shelf = InventoryItem.tenant_id == tenant_id, InventoryItem.is_active.is_(True)
    inventory = (
        await db.execute(
            select(
                func.count().label("items"),
                func.count().filter(InventoryItem.is_visible.is_(True)).label("visible"),
                func.count().filter(InventoryItem.quantity == 0).label("out_of_stock"),
            ).where(*shelf)
        )
    ).one()

    kept_count = totals.kept or 0
    return StoreStatsOut(
        days=days,
        since=first_day,
        orders=sum(by_status.values()),
        by_status={status: by_status.get(status, 0) for status in OrderStatus},
        by_channel={channel: by_channel.get(channel, 0) for channel in OrderChannel},
        sales=totals.sales,
        completed_sales=totals.completed,
        average_order=totals.sales // kept_count if kept_count else 0,
        customers=customers.all,
        returning_customers=customers.returning,
        by_day=by_day,
        top_books=[
            TopBookOut(book_id=row.book_id, title=row.title, quantity=row.quantity, sales=row.sales)
            for row in top
        ],
        inventory=InventoryStatsOut(
            items=inventory.items, visible=inventory.visible, out_of_stock=inventory.out_of_stock
        ),
    )
