"""422 messages are sentences in the request's language, never pydantic's English."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.catalog import BookCreate
from schemas.inventory import InventoryItemCreate
from schemas.tenant import TenantUpdate
from tests.factories import make_tenant, make_user, sign_in
from translations import FIELD_LABELS, Msg
from utils.i18n import Lang
from utils.validation import explain


def first(model: type, lang: Lang = Lang.uz, **data: object) -> tuple[str, str]:
    with pytest.raises(ValidationError) as caught:
        model(**data)
    error = caught.value.errors()[0]
    return error["type"], explain(error, lang)


def test_our_problems_have_their_own_type_and_text() -> None:
    assert first(TenantUpdate, phone="12") == (
        "phone_invalid",
        "Telefon raqam notoʻgʻri. Masalan: 90 123 45 67 yoki +998 90 123 45 67.",
    )
    kind, text = first(BookCreate, Lang.ru, title="X", authors=["A"], isbn="978-9943-55-123-4")
    assert kind == "isbn_check_digit" and "должна быть 7" in text
    kind, text = first(BookCreate, Lang.en, title="X", authors=["A"], isbn="12345")
    assert kind == "isbn_invalid" and text.startswith("Invalid ISBN")


def test_pydantic_problems_are_translated_with_the_field_name() -> None:
    assert first(TenantUpdate, accent_color="red")[1] == "Rang #RRGGBB koʻrinishida boʻlsin, masalan #2B3BD1."
    assert first(TenantUpdate, card_number="8600")[1] == "Karta raqami 16 ta raqamdan iborat boʻlsin."
    assert first(TenantUpdate, Lang.ru, delivery_fee=-1)[1] == "Стоимость доставки: Не меньше 0."
    assert first(TenantUpdate, name="X")[1] == "Nomi: Kamida 2 ta belgi boʻlsin."
    assert first(InventoryItemCreate, book_id=1, price=0)[1] == "Narx 0 dan katta boʻlsin."
    assert first(InventoryItemCreate, Lang.en, book_id="x", price=100)[1] == "Enter a number."


@pytest.mark.parametrize("bad", ["String should", "Value error", "must be", "pattern"])
@pytest.mark.parametrize(
    "data",
    [
        {"phone": "1"},
        {"card_number": "1"},
        {"accent_color": "x"},
        {"latitude": 1},
        {"languages": ["uz", "uz"]},
    ],
)
def test_no_english_leaks_into_uzbek(bad: str, data: dict) -> None:
    assert bad not in first(TenantUpdate, **data)[1]


def test_every_field_label_has_three_languages() -> None:
    for labels in FIELD_LABELS.values():
        assert set(labels) == set(Lang)
    assert Msg.TOO_SHORT.value != "too_short"  # pydantic's own type name stays pydantic's


@pytest.mark.db
async def test_owner_sees_uzbek_messages(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    resp = await client.patch(f"/tenants/{tenant.id}", json={"card_number": "8600 12"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["message"] == "Karta raqami 16 ta raqamdan iborat boʻlsin."
    ok = await client.patch(f"/tenants/{tenant.id}", json={"phone": "90 123 45 67"})
    assert ok.status_code == 200 and ok.json()["phone"] == "+998901234567"
