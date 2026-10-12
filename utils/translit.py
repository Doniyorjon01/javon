"""
Transliteration and search keys
===============================
Uzbek is written in two scripts and Russian titles are common, so the same book
may be typed as "O'tkan kunlar", "Ўтган кунлар" or "Otkan kunlar". Everything we
compare or index is first brought to one form:

    to_ascii_latin("Ўтган кунлар")   -> "otgan kunlar"
    search_key("Abdulla Qodiriy — O'tkan kunlar!") -> "abdulla qodiriy otkan kunlar"

Rules: lowercase; Uzbek and Russian Cyrillic -> Uzbek Latin; apostrophe-like marks
inside words dropped (o'zbek -> ozbek, not o zbek); accents stripped (café -> cafe);
anything else non-latin removed.

The stored search_text and the user's query go through the SAME function, so
imperfect transliteration (Russian "х" -> "x", not "kh") still matches itself.
Changing these rules changes stored data: add a migration that recomputes
books.search_text in the same commit.
"""

import re
import unicodedata

# Uzbek and Russian Cyrillic -> Uzbek Latin. Multi-letter values on purpose (ш -> sh).
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}  # fmt: skip

# Apostrophe-like marks used inside Uzbek words (o'zbek, gʻoya).
_APOSTROPHES = re.compile("['`´ʻʼ‘’]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def to_ascii_latin(text: str) -> str:
    """Lowercase ASCII Latin; punctuation and spaces are kept for the caller to handle."""
    s = _APOSTROPHES.sub("", text.strip().lower())
    s = "".join(CYRILLIC_TO_LATIN.get(ch, ch) for ch in s)
    # Remaining accents: "café" -> "cafe"; anything non-latin is dropped.
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def search_key(*parts: str | None) -> str:
    """Words of all parts in one normalized, space-separated string. "" if nothing usable."""
    text = " ".join(part for part in parts if part)
    return " ".join(_NON_ALNUM.sub(" ", to_ascii_latin(text)).split())
