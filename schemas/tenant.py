"""
Tenant (store) schemas
======================
TenantCreate   wizard step "Do'kon nomi": name + slug. Status, plan and trial
               dates are set by the server, never by the client.
TenantUpdate   wizard steps "Ko'rinish" and "Ma'lumotlar". extra="forbid": a
               request that tries to send status/plan/slug fails with 422
               instead of being silently ignored.
StorefrontOut  what any visitor of the store may see.
TenantOut      what the store's owner sees in the admin panel.
"""

import re
from datetime import datetime, time
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from models.tenant import Plan, TenantStatus
from schemas.base import ORMModel
from utils.i18n import Lang
from utils.slug import SLUG_MAX_LENGTH, SLUG_MIN_LENGTH, SLUG_PATTERN

_PHONE_SEPARATORS = re.compile(r"[\s\-()]")
_PHONE_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _normalize_phone(value: str) -> str:
    value = _PHONE_SEPARATORS.sub("", value)
    if not _PHONE_RE.match(value):
        raise ValueError("phone must be in international format, e.g. +998901234567")
    return value


def _strip_at(value: str) -> str:
    return value.removeprefix("@")


Phone = Annotated[str, AfterValidator(_normalize_phone)]
Slug = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(min_length=SLUG_MIN_LENGTH, max_length=SLUG_MAX_LENGTH, pattern=SLUG_PATTERN),
]
StoreName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Address = Annotated[str, StringConstraints(max_length=255)]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
ThemeKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]
TelegramUsername = Annotated[
    str, AfterValidator(_strip_at), StringConstraints(pattern=r"^@?[A-Za-z][A-Za-z0-9_]{4,31}$")
]
InstagramUsername = Annotated[
    str, AfterValidator(_strip_at), StringConstraints(pattern=r"^@?[A-Za-z0-9._]{1,30}$")
]


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class DayHours(BaseModel):
    open: time
    close: time

    @model_validator(mode="after")
    def _open_before_close(self) -> Self:
        if self.open >= self.close:
            raise ValueError("open must be earlier than close")
        return self


# None for a day = closed that day. A missing day = not specified.
WorkingHours = dict[Weekday, DayHours | None]


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StoreName
    slug: Slug


class TenantUpdate(BaseModel):
    """Every field optional; apply with model_dump(exclude_unset=True). Empty string clears a field."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: StoreName | None = None
    theme: ThemeKey | None = None
    accent_color: HexColor | None = None
    phone: Annotated[Phone | None, BeforeValidator(_empty_to_none)] = None
    address: Annotated[Address | None, BeforeValidator(_empty_to_none)] = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    working_hours: WorkingHours | None = None
    telegram_username: Annotated[TelegramUsername | None, BeforeValidator(_empty_to_none)] = None
    instagram_username: Annotated[InstagramUsername | None, BeforeValidator(_empty_to_none)] = None
    languages: list[Lang] | None = Field(default=None, min_length=1)

    @field_validator("languages")
    @classmethod
    def _unique_languages(cls, value: list[Lang] | None) -> list[Lang] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("languages must not repeat")
        return value

    @model_validator(mode="after")
    def _location_pair(self) -> Self:
        sent = self.model_fields_set
        if ("latitude" in sent) != ("longitude" in sent):
            raise ValueError("latitude and longitude must be sent together")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be empty")
        return self


class StorefrontOut(ORMModel):
    slug: str
    name: str
    theme: str
    accent_color: str
    phone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    working_hours: WorkingHours | None
    telegram_username: str | None
    instagram_username: str | None
    languages: list[Lang]


class TenantOut(StorefrontOut):
    id: int
    status: TenantStatus
    plan: Plan
    trial_ends_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SlugCheckOut(BaseModel):
    slug: str
    available: bool
    reason: Literal["invalid", "reserved", "taken"] | None = None
    suggestions: list[str] = []