"""
Buyer phone numbers
===================
Buyers type numbers however they like; we store E.164 ("+998901234567") so one
person is one customer per store and the CHECK constraints hold.

    "+998 90 123-45-67" -> "+998901234567"
    "998901234567"      -> "+998901234567"
    "90 123 45 67"      -> "+998901234567"   (local Uzbek number: 9 digits)
    "+7 912 345 67 89"  -> "+79123456789"    (other countries keep their code)
"""

import re

_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
UZ_CODE = "998"


def normalize_phone(value: str) -> str:
    """Raises ValueError when it cannot be a phone number."""
    digits = _SEPARATORS.sub("", value.strip())
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        if len(digits) == 9 and digits.isdigit():
            digits = UZ_CODE + digits
        digits = "+" + digits
    if not _E164.match(digits) or (digits.startswith("+" + UZ_CODE) and len(digits) != 13):
        raise ValueError("phone must be a valid number, e.g. +998901234567")
    return digits


def mask_phone(phone: str) -> str:
    """ "+998901234567" -> "+998 ** *** 45 67": enough for the buyer to recognise it."""
    return f"{phone[:4]} ** *** {phone[-4:-2]} {phone[-2:]}"
