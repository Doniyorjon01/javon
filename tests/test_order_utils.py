"""Buyer phone numbers, order tracking tokens and Excel value parsing."""

import pytest

from services.excel import parse_quantity, parse_som, split_authors
from utils.phone import mask_phone, normalize_phone
from utils.signing import check_order_token, order_token


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123-45-67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("90 123 45 67", "+998901234567"),
        ("(90) 123-45-67", "+998901234567"),
        ("00998901234567", "+998901234567"),
        ("+7 912 345 67 89", "+79123456789"),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12", "+998 90 123", "+998 90 123 45 678", "abc", "+0123456789"])
def test_bad_phones(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_mask_phone() -> None:
    assert mask_phone("+998901234567") == "+998 ** *** 45 67"


def test_order_token_is_bound_to_store_and_order() -> None:
    token = order_token(1, 42)
    assert len(token) == 22
    assert check_order_token(1, 42, token)
    assert not check_order_token(1, 43, token)
    assert not check_order_token(2, 42, token)


@pytest.mark.parametrize(
    ("text", "tiyin"),
    [
        ("45000", 4_500_000),
        ("45 000", 4_500_000),
        ("45,000", 4_500_000),
        ("45000.50", 4_500_050),
        ("45000,5", 4_500_050),
        ("45 000 so'm", 4_500_000),
        ("12 000 сум", 1_200_000),
        ("0", 0),
        ("bepul", None),
        ("-5", None),
        ("", None),
    ],
)
def test_parse_som(text: str, tiyin: int | None) -> None:
    assert parse_som(text) == tiyin


@pytest.mark.parametrize(
    ("text", "number"), [("3", 3), ("1 000", 1000), ("2.5", None), ("-1", None), ("x", None)]
)
def test_parse_quantity(text: str, number: int | None) -> None:
    assert parse_quantity(text) == number


def test_split_authors() -> None:
    assert split_authors("Abdulla Qodiriy; Cho'lpon") == ["Abdulla Qodiriy", "Cho'lpon"]
    assert split_authors("A Bir, B Ikki") == ["A Bir", "B Ikki"]
    assert split_authors("Qodiriy, Abdulla; Cho'lpon") == ["Qodiriy, Abdulla", "Cho'lpon"]
