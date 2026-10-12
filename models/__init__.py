"""
Every model module is imported here, so `Base.metadata` is complete for Alembic.
Add the import when you add a module.
"""

from models.base import Base, BaseModel
from models.catalog import Author, Book, BookAuthor, BookLanguage, BookStatus, Publisher
from models.tenant import MemberRole, Membership, Plan, Tenant, TenantStatus
from models.user import User, UserSession

__all__ = [
    "Author",
    "Base",
    "BaseModel",
    "Book",
    "BookAuthor",
    "BookLanguage",
    "BookStatus",
    "MemberRole",
    "Membership",
    "Plan",
    "Publisher",
    "Tenant",
    "TenantStatus",
    "User",
    "UserSession",
]
