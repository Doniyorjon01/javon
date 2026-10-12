import pytest

from utils.isbn import looks_like_isbn, normalize_isbn


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9780306406157", "9780306406157"),
        ("978-0-306-40615-7", "9780306406157"),
        (" 978 0 306 40615 7 ", "9780306406157"),
        ("ISBN 978-0-306-40615-7", "9780306406157"),
        ("ISBN:9780306406157", "9780306406157"),
        ("0-306-40615-2", "9780306406157"),  # ISBN-10 -> ISBN-13
        ("080442957X", "9780804429573"),  # ISBN-10 with X check digit
        ("080442957x", "9780804429573"),
        ("9791090636071", "9791090636071"),  # 979 prefix
        ("9789943000001", "9789943000001"),
    ],
)
def test_valid(raw: str, expected: str) -> None:
    assert normalize_isbn(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "9780306406158",  # wrong check digit
        "0-306-40615-3",  # wrong ISBN-10 check digit
        "9770306406157",  # EAN-13 but not a book (977 = magazines)
        "4600000000000",  # a grocery barcode
        "97803064061",  # too short
        "97803064061570",  # too long
        "X306406152",  # X only allowed last
        "abcdefghij",
        "",
    ],
)
def test_invalid(raw: str) -> None:
    assert normalize_isbn(raw) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("978-0-306-40615-7", True),
        ("0306406152", True),
        ("080442957X", True),
        ("qodiriy", False),
        ("1984", False),  # a title, not an ISBN
        ("978 kitob", False),
    ],
)
def test_looks_like_isbn(text: str, expected: bool) -> None:
    assert looks_like_isbn(text) is expected
