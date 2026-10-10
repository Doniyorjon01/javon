"""
Every model module is imported here, so `Base.metadata` is complete for Alembic.
Add the import when you add a module.
"""

from models.base import Base, BaseModel

__all__ = ["Base", "BaseModel"]
