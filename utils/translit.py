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
books.search_text, books.dedupe_key and the authors/publishers search_key in
the same commit.

detect_script() tells a Latin edition from a Cyrillic one; book_dedupe_key()
is the identity of a book without an ISBN (see models/catalog.py).
"""

import re
import unicodedata
from typing import Literal

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


Script = Literal["latn", "cyrl", "other"]


def detect_script(text: str) -> Script:
    """
    Which alphabet `text` is written in, by majority of its letters:
    "O'tkan kunlar" -> "latn", "Ўтган кунлар" -> "cyrl", "1984" -> "other".

    search_key() deliberately makes the Latin and Cyrillic editions of a book look
    the same; this is what still tells them apart (they are different products).
    """
    latin = cyrillic = 0
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("LATIN"):
            latin += 1
        elif name.startswith("CYRILLIC"):
            cyrillic += 1
    if latin == cyrillic:  # no letters at all, or a perfect tie
        return "other"
    return "latn" if latin > cyrillic else "cyrl"


def book_dedupe_key(
    *,
    language: str,
    script: str,
    title: str,
    subtitle: str | None,
    authors: list[str],
    publisher: str | None,
) -> str:
    """
    Identity of a book that has no ISBN: two submissions with the same key are
    the same edition. Author order and spelling ("Qodiriy" / "Қодирий") do not
    matter; the alphabet the book is printed in and the publisher do.

        "uz|latn|otkan kunlar|abdulla qodiriy|sharq"
    """
    author_keys = ";".join(sorted(search_key(name) for name in authors))
    return "|".join((language, script, search_key(title, subtitle), author_keys, search_key(publisher)))
