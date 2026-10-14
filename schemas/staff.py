"""
Staff schemas
=============
InviteCreatedOut   the link, shown once: only its hash is stored
InviteOut          an open invite in the owner's list (no link)
InvitePreviewOut   what the invited person sees before accepting
MemberOut          someone who works in the store
"""

from datetime import datetime

from pydantic import BaseModel

from models.tenant import MemberRole
from schemas.base import ORMModel


class InviteCreatedOut(BaseModel):
    id: int
    url: str  # APP_URL/taklif/<token>: send it to the colleague
    expires_at: datetime


class InviteOut(ORMModel):
    id: int
    created_at: datetime
    expires_at: datetime


class InvitePreviewOut(BaseModel):
    store_name: str
    store_slug: str
    expires_at: datetime


class JoinedStoreOut(BaseModel):
    tenant_id: int
    slug: str
    name: str
    role: MemberRole


class MemberOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    phone: str | None
    role: MemberRole
    joined_at: datetime
