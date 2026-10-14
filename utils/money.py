"""
Money for people
================
The API speaks tiyin (integers); messages for people speak so'm:

    format_som(12_050_000, Lang.uz) -> "120 500 so'm"
    format_som(12_050_050, Lang.ru) -> "120 500,50 сум"
"""

from utils.i18n import Lang

_CURRENCY = {Lang.uz: "so'm", Lang.ru: "сум", Lang.en: "UZS"}
_THIN_SPACE = "\u202f"  # narrow no-break space: keeps "120 500" on one line


def format_som(tiyin: int, lang: Lang = Lang.uz) -> str:
    som, rest = divmod(abs(tiyin), 100)
    whole = f"{som:,}".replace(",", _THIN_SPACE)
    decimal = "," if lang != Lang.en else "."
    amount = f"{whole}{decimal}{rest:02d}" if rest else whole
    sign = "-" if tiyin < 0 else ""
    return f"{sign}{amount} {_CURRENCY[lang]}"
