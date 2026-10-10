"""
Model base
==========
`BaseModel` gives every table the columns hik-backend's base had:
id, is_active, created_at, updated_at.

Differences from hik:
  * SQLAlchemy 2 typed columns (`Mapped[...]`), so the type checker sees them;
  * BIGINT identity ids;
  * timezone-aware timestamps, filled by the database, not by Python;
  * a naming convention, so Alembic generates stable, predictable constraint names;
  * eager_defaults: server-generated values come back via RETURNING on insert.
    In async code a lazy reload of `created_at` would raise MissingGreenlet.

Soft delete (`is_active = False`) is the default, as in hik. Two rules follow:
  * a UNIQUE constraint on a soft-deletable table must be a partial index
    `WHERE is_active` — otherwise a deleted row blocks re-creating it;
  * money and order history are never soft-deleted; those tables override this
    with explicit status columns.
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, func, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class BaseModel(Base):
    __abstract__ = True
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # No index of its own: low cardinality. Filter it inside composite or partial indexes.
    is_active: Mapped[bool] = mapped_column(server_default=true(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
