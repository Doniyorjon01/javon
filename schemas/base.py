"""
Schema base
===========
Naming per entity, as in hik-backend:

    XBase     shared fields
    XCreate   what the client may send on create (never tenant_id, id, status set by the server)
    XUpdate   every field Optional; apply with data.model_dump(exclude_unset=True)
    XOut      what the API returns
    XOutFull  XOut plus nested relations (only where the screen needs them)

Pydantic v2 style: `model_config = ConfigDict(...)`, not the v1 `class Config`.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# Largest value of a PostgreSQL BIGINT. Ids from the outside are checked against it,
# so an over-long number is a 422 instead of a database error (500).
BIGINT_MAX = 2**63 - 1


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedOut(ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime
