"""
ISBN
====
The catalog stores one form only: ISBN-13 digits, no hyphens ("9789943000000").

    normalize_isbn("978-9943-00-000-0")  -> "9789943000000"
    normalize_isbn("0-306-40615-2")      -> "9780306406157"   (ISBN-10 converted)
    normalize_isbn("9789943000001")      -> None              (wrong check digit)

A phone camera reading the barcode on the back cover gets the EAN-13, which for
books is exactly the ISBN-13 (prefix 978 or 979).

Many Uzbek books have no ISBN at all, so the catalog field is optional; when it
is given, it must be a real one.
"""

import re

_SEPARATORS = re.compile(r"[\s\-]")


def _isbn13_check_digit(first12: str) -> int:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return (10 - total % 10) % 10


def _isbn10_is_valid(isbn10: str) -> bool:
    if not re.fullmatch(r"[0-9]{9}[0-9X]", isbn10):
        return False
    digits = [10 if ch == "X" else int(ch) for ch in isbn10]
    return sum((10 - i) * d for i, d in enumerate(digits)) % 11 == 0


def normalize_isbn(raw: str) -> str | None:
    """ISBN-13 digits, or None if `raw` is not a valid ISBN-10 or ISBN-13."""
    value = _clean(raw)
    if re.fullmatch(r"97[89][0-9]{10}", value):
        return value if _isbn13_check_digit(value[:12]) == int(value[12]) else None

    if len(value) == 10 and _isbn10_is_valid(value):
        first12 = "978" + value[:9]
        return first12 + str(_isbn13_check_digit(first12))

    return None


def _clean(raw: str) -> str:
    value = _SEPARATORS.sub("", raw).upper()
    return value.removeprefix("ISBN").lstrip(":") if value.startswith("ISBN") else value


def expected_check_digit(raw: str) -> str | None:
    """
    For an ISBN whose only fault is its last digit: the digit it should end with
    ("9789943551234" -> "8"), so the message can say exactly what is wrong.
    None when the value is not ISBN-shaped at all (wrong length, letters...).
    """
    value = _clean(raw)
    if re.fullmatch(r"97[89][0-9]{10}", value):
        return str(_isbn13_check_digit(value[:12]))
    if re.fullmatch(r"[0-9]{9}[0-9X]", value):
        total = sum((10 - i) * int(d) for i, d in enumerate(value[:9]))
        check = (11 - total % 11) % 11
        return "X" if check == 10 else str(check)
    return None


def looks_like_isbn(text: str) -> bool:
    """Is a search query an ISBN rather than words? (digits, hyphens, optional final X)."""
    value = _SEPARATORS.sub("", text).upper()
    return bool(re.fullmatch(r"[0-9]{9}[0-9X]|[0-9]{13}", value))
