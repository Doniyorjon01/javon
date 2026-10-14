"""
Every model module is imported here, so `Base.metadata` is complete for Alembic.
Add the import when you add a module.
"""

from models.base import Base, BaseModel
from models.catalog import (
    Author,
    Book,
    BookAuthor,
    BookLanguage,
    BookScript,
    BookSource,
    BookStatus,
    Publisher,
)
from models.inventory import ImportStatus, InventoryImport, InventoryItem
from models.job import Job, JobStatus
from models.order import (
    Customer,
    DeliveryType,
    Order,
    OrderChannel,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from models.telegram import BotStatus, TelegramBot
from models.tenant import MemberRole, Membership, Plan, Tenant, TenantStatus
from models.user import User, UserSession

__all__ = [
    "Author",
    "Base",
    "BaseModel",
    "Book",
    "BookAuthor",
    "BookLanguage",
    "BookScript",
    "BookSource",
    "BookStatus",
    "BotStatus",
    "Customer",
    "DeliveryType",
    "ImportStatus",
    "InventoryImport",
    "InventoryItem",
    "Job",
    "JobStatus",
    "MemberRole",
    "Membership",
    "Order",
    "OrderChannel",
    "OrderItem",
    "OrderStatus",
    "PaymentMethod",
    "PaymentStatus",
    "Plan",
    "Publisher",
    "TelegramBot",
    "Tenant",
    "TenantStatus",
    "User",
    "UserSession",
]
