"""
Validation messages people can read
===================================
Pydantic's own messages are English and technical ("String should match pattern
'^[0-9]{16}$'"). Two pieces turn every 422 into one sentence in the request's
language:

  * our validators raise invalid(Msg.PHONE_INVALID) instead of ValueError("..."):
    the Msg value becomes the error's "type", so the reason is machine-readable;
  * explain(error, lang) (used by errors.py) translates any pydantic error:
    our types by their Msg, pydantic's built-in types by a small table, a few
    fields by their meaning (a pattern mismatch on "phone" is a bad phone
    number), and puts the field's name in front: «Telefon: ...».

    {"type": "phone_invalid", "loc": ["body", "phone"],
     "msg": "Telefon: Telefon raqam noto'g'ri. Masalan: 90 123 45 67 ..."}
"""

from typing import Any

from pydantic_core import PydanticCustomError

from translations import FIELD_LABELS, Msg, translate
from utils.i18n import Lang
from utils.isbn import expected_check_digit, normalize_isbn
from utils.phone import normalize_phone


def invalid(msg: Msg, *values: object) -> PydanticCustomError:
    """Raise from a validator: the type is msg.value, the English text is a fallback."""
    text = translate(msg, Lang.en).format(*values) if values else translate(msg, Lang.en)
    return PydanticCustomError(msg.value, text, {"values": list(values)})


# --------------------------------------------------------------------------- #
# Reusable validators
# --------------------------------------------------------------------------- #
def phone(value: str) -> str:
    """Any way people write an Uzbek or international number -> "+998901234567"."""
    try:
        return normalize_phone(value)
    except ValueError:
        raise invalid(Msg.PHONE_INVALID) from None


def isbn(value: str) -> str:
    """A valid ISBN-10/13 -> ISBN-13 digits; a wrong check digit says which one is right."""
    isbn13 = normalize_isbn(value)
    if isbn13 is not None:
        return isbn13
    expected = expected_check_digit(value)
    if expected is not None:
        raise invalid(Msg.ISBN_CHECK_DIGIT, expected)
    raise invalid(Msg.ISBN_INVALID)


# --------------------------------------------------------------------------- #
# Translating any pydantic error
# --------------------------------------------------------------------------- #
_BY_TYPE: dict[str, tuple[Msg, str | None]] = {
    # pydantic type -> (our message, the ctx value that fills its {})
    "missing": (Msg.FIELD_REQUIRED, None),
    "string_too_short": (Msg.TOO_SHORT, "min_length"),
    "string_too_long": (Msg.TOO_LONG, "max_length"),
    "too_short": (Msg.LIST_TOO_SHORT, "min_length"),
    "too_long": (Msg.LIST_TOO_LONG, "max_length"),
    "string_pattern_mismatch": (Msg.WRONG_FORMAT, None),
    "int_parsing": (Msg.NOT_A_NUMBER, None),
    "int_type": (Msg.NOT_A_NUMBER, None),
    "int_from_float": (Msg.NOT_A_NUMBER, None),
    "float_parsing": (Msg.NOT_A_NUMBER, None),
    "float_type": (Msg.NOT_A_NUMBER, None),
    "decimal_parsing": (Msg.NOT_A_NUMBER, None),
    "greater_than": (Msg.NUMBER_ABOVE, "gt"),
    "greater_than_equal": (Msg.NUMBER_MIN, "ge"),
    "less_than": (Msg.NUMBER_MAX, "lt"),
    "less_than_equal": (Msg.NUMBER_MAX, "le"),
    "enum": (Msg.NOT_ALLOWED_VALUE, None),
    "literal_error": (Msg.NOT_ALLOWED_VALUE, None),
    "extra_forbidden": (Msg.UNKNOWN_FIELD, None),
    "json_invalid": (Msg.BAD_REQUEST_BODY, None),
    "json_type": (Msg.BAD_REQUEST_BODY, None),
    "model_attributes_type": (Msg.BAD_REQUEST_BODY, None),
    "dict_type": (Msg.BAD_REQUEST_BODY, None),
    "list_type": (Msg.BAD_REQUEST_BODY, None),
    "bool_parsing": (Msg.NOT_BOOL, None),
    "bool_type": (Msg.NOT_BOOL, None),
    "string_type": (Msg.INVALID_VALUE, None),
    "uuid_parsing": (Msg.WRONG_FORMAT, None),
    "uuid_type": (Msg.WRONG_FORMAT, None),
}

# A pattern mismatch means something specific on these fields.
_PATTERN_BY_FIELD: dict[str, Msg] = {
    "phone": Msg.PHONE_INVALID,
    "card_number": Msg.CARD_NUMBER_INVALID,
    "accent_color": Msg.COLOR_INVALID,
    "slug": Msg.SLUG_INVALID,
    "telegram_username": Msg.USERNAME_INVALID,
    "instagram_username": Msg.USERNAME_INVALID,
    "isbn": Msg.ISBN_INVALID,
}

# Our own error types; a name pydantic also uses ("too_short") is pydantic's.
_OUR_TYPES = {msg.value: msg for msg in Msg if msg.value not in _BY_TYPE}

# These already name what they are about ("Telefon raqam noto'g'ri..."): no «Telefon:» in front.
_SELF_DESCRIBING = frozenset(
    {
        Msg.PHONE_INVALID,
        Msg.CARD_NUMBER_INVALID,
        Msg.ISBN_INVALID,
        Msg.ISBN_CHECK_DIGIT,
        Msg.COLOR_INVALID,
        Msg.SLUG_INVALID,
        Msg.PRICE_POSITIVE,
        Msg.DUPLICATE_ORDER_LINES,
        Msg.ADDRESS_REQUIRED,
        Msg.LOCATION_PAIR,
        Msg.REFUSAL_NOTE_REQUIRED,
        Msg.HOURS_ORDER,
        Msg.LANGUAGES_REPEAT,
        Msg.AUTHOR_REPEAT,
        Msg.BOOK_LANGUAGE_INVALID,
        Msg.BOOK_SCRIPT_INVALID,
    }
)


def _field(loc: tuple[Any, ...] | list[Any]) -> str | None:
    """The innermost named field: ("body", "items", 0, "quantity") -> "quantity"."""
    for part in reversed(list(loc)):
        if isinstance(part, str) and part not in ("body", "query", "path"):
            return part
    return None


def _date_type(kind: str) -> bool:
    return kind.startswith(("datetime_", "date_", "time_", "timezone_"))


def explain(error: dict[str, Any], lang: Lang) -> str:
    kind = str(error.get("type", ""))
    ctx = error.get("ctx") or {}
    field = _field(error.get("loc", ()))

    if kind in _OUR_TYPES:
        msg = _OUR_TYPES[kind]
        text = translate(msg, lang).format(*ctx.get("values", []))
        if msg in _SELF_DESCRIBING:
            return text
    elif field == "price" and kind in ("greater_than", "greater_than_equal"):
        return translate(Msg.PRICE_POSITIVE, lang)
    elif kind == "string_pattern_mismatch" and field in _PATTERN_BY_FIELD:
        return translate(_PATTERN_BY_FIELD[field], lang)
    elif kind in _BY_TYPE:
        msg, key = _BY_TYPE[kind]
        template = translate(msg, lang)
        text = template.format(ctx.get(key, "")) if key else template
    elif _date_type(kind):
        text = translate(Msg.BAD_DATE, lang)
    else:
        text = translate(Msg.INVALID_VALUE, lang)

    label = FIELD_LABELS.get(field or "", {}).get(lang)
    return f"{label}: {text}" if label else text
