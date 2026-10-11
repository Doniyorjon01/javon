"""
User and sign-in schemas
========================
TelegramLoginIn  the Telegram Login Widget payload, passed through UNCHANGED:
                 every field except `hash` is part of the signature, so unknown
                 fields are kept (extra="allow") and nothing is stripped or trimmed.
DevLoginIn       local development and tests only (settings.dev_login_enabled).
MeOut            who is signed in and which stores they can open.
"""

from pydantic import BaseModel, ConfigDict, Field

from models.tenant import MemberRole, TenantStatus
from schemas.base import ORMModel


class TelegramLoginIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=64)
    photo_url: str | None = Field(default=None, max_length=512)
    auth_date: int
    hash: str = Field(min_length=64, max_length=64)

    def signed_payload(self) -> dict[str, object]:
        """Exactly the fields Telegram signed, extras included."""
        return self.model_dump(exclude_none=True)


class DevLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    phone: str | None
    language: str
    is_platform_admin: bool


class MyStoreOut(ORMModel):
    tenant_id: int
    slug: str
    name: str
    status: TenantStatus
    role: MemberRole


class MeOut(BaseModel):
    user: UserOut
    stores: list[MyStoreOut]
