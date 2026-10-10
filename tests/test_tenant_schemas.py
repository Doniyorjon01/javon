import pytest
from pydantic import ValidationError

from schemas.tenant import TenantCreate, TenantUpdate


def test_create_normalizes_slug() -> None:
    data = TenantCreate(name="  Varaq  ", slug="  Varaq ")
    assert data.name == "Varaq"
    assert data.slug == "varaq"


@pytest.mark.parametrize("field", ["status", "plan", "trial_ends_at", "id"])
def test_create_rejects_server_owned_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        TenantCreate(name="Varaq", slug="varaq", **{field: "x"})


@pytest.mark.parametrize("field", ["status", "plan", "slug", "logo_key"])
def test_update_rejects_server_owned_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        TenantUpdate(**{field: "x"})


def test_update_normalizes_phone() -> None:
    assert TenantUpdate(phone="+998 (90) 123-45-67").phone == "+998901234567"


@pytest.mark.parametrize("phone", ["901234567", "+0123456789", "+998abc", "+1234"])
def test_update_rejects_bad_phone(phone: str) -> None:
    with pytest.raises(ValidationError):
        TenantUpdate(phone=phone)


def test_update_empty_string_clears_field() -> None:
    data = TenantUpdate(phone="", address="  ", telegram_username="")
    assert data.model_dump(exclude_unset=True) == {"phone": None, "address": None, "telegram_username": None}


def test_update_strips_at_from_usernames() -> None:
    data = TenantUpdate(telegram_username="@varaq_books", instagram_username="@varaq.books")
    assert data.telegram_username == "varaq_books"
    assert data.instagram_username == "varaq.books"


def test_update_location_must_come_in_pairs() -> None:
    with pytest.raises(ValidationError):
        TenantUpdate(latitude=41.3)
    with pytest.raises(ValidationError):
        TenantUpdate(latitude=41.3, longitude=None)
    assert TenantUpdate(latitude=41.31, longitude=69.24).latitude == 41.31
    assert TenantUpdate(latitude=None, longitude=None).model_dump(exclude_unset=True) == {
        "latitude": None,
        "longitude": None,
    }


def test_update_working_hours() -> None:
    data = TenantUpdate(working_hours={"mon": {"open": "09:00", "close": "20:00"}, "sun": None})
    dumped = data.model_dump(exclude_unset=True, mode="json")
    assert dumped["working_hours"] == {"mon": {"open": "09:00:00", "close": "20:00:00"}, "sun": None}


@pytest.mark.parametrize(
    "hours",
    [
        {"mon": {"open": "20:00", "close": "09:00"}},  # closes before it opens
        {"mon": {"open": "09:00", "close": "09:00"}},
        {"monday": {"open": "09:00", "close": "20:00"}},  # unknown day key
    ],
)
def test_update_rejects_bad_working_hours(hours: dict) -> None:
    with pytest.raises(ValidationError):
        TenantUpdate(working_hours=hours)


def test_update_languages() -> None:
    assert TenantUpdate(languages=["uz", "ru"]).languages == ["uz", "ru"]
    for bad in ([], ["uz", "uz"], ["de"]):
        with pytest.raises(ValidationError):
            TenantUpdate(languages=bad)