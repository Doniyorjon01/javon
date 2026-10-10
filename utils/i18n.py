"""
Request language
================
`lang: Lang = Depends(get_lang)` in every route, same as hik-backend.

Differences from hik:
  * default is Uzbek — the product's primary language;
  * q-values are honoured: "ru;q=0.1, en;q=0.9" picks English, not Russian.
"""

from enum import StrEnum

from fastapi import Request


class Lang(StrEnum):
    uz = "uz"  # O'zbekcha (lotin)
    ru = "ru"  # Русский
    en = "en"  # English


SUPPORTED = {lang.value for lang in Lang}
DEFAULT_LANG = Lang.uz


def parse_accept_language(header: str | None) -> Lang:
    if not header:
        return DEFAULT_LANG

    candidates: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue

        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            continue

        # Higher q first; equal q keeps header order.
        candidates.append((-quality, position, tag))

    for _, _, tag in sorted(candidates):
        primary = tag.split("-")[0]  # uz-Latn-UZ -> uz, en-US -> en
        if primary in SUPPORTED:
            return Lang(primary)
    return DEFAULT_LANG


def get_lang(request: Request) -> Lang:
    return parse_accept_language(request.headers.get("accept-language"))
