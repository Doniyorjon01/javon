"""
Statistics schemas
==================
StoreStatsOut      the owner's dashboard: orders, sales, best sellers, shelf
PlatformMetricsOut the platform admin's numbers (the weekly KPIs from the plan)
"""

from datetime import date

from pydantic import BaseModel

from models.order import OrderChannel, OrderStatus
from utils.plans import AccessState


class DayStatsOut(BaseModel):
    day: date  # Tashkent calendar day
    orders: int  # not cancelled
    sales: int  # tiyin, not cancelled


class TopBookOut(BaseModel):
    book_id: int
    title: str
    quantity: int
    sales: int


class InventoryStatsOut(BaseModel):
    items: int
    visible: int
    out_of_stock: int


class StoreStatsOut(BaseModel):
    days: int
    since: date
    orders: int  # all statuses
    by_status: dict[OrderStatus, int]
    by_channel: dict[OrderChannel, int]
    sales: int  # tiyin; orders not cancelled
    completed_sales: int  # tiyin; completed orders only
    average_order: int  # tiyin; sales / orders not cancelled
    customers: int  # distinct buyers in the period
    returning_customers: int  # of those, with more than one order
    by_day: list[DayStatsOut]
    top_books: list[TopBookOut]
    inventory: InventoryStatsOut


class PlatformMetricsOut(BaseModel):
    stores: int  # not deleted
    by_access: dict[AccessState, int]
    launched: int
    new_stores_7d: int
    new_stores_30d: int
    active_stores_7d: int  # at least one order in 7 days (the plan's "faol do'kon")
    orders_7d: int
    orders_30d: int
    sales_30d: int  # tiyin, not cancelled
    paying_stores: int  # paid period running now
    revenue_30d: int  # tiyin, subscription payments recorded in 30 days
    books_pending: int  # catalogue moderation queue
    jobs_failed: int
    jobs_queued: int
