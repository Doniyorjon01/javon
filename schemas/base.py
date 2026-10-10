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


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedOut(ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime
