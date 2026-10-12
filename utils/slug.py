"""
Store slugs
===========
A slug is the store's subdomain: varaq.javon.uz -> "varaq". It is also the key
the storefront API is addressed by (/storefront/{slug}).

Rules (mirrored by a CHECK constraint on tenants.slug):
  * 3-40 characters, lowercase latin letters, digits and single hyphens;
  * starts with a letter, does not end with a hyphen;
  * not one of RESERVED_SLUGS (platform subdomains and confusing names).

Once taken, a slug is never released, even if the store is deleted:
otherwise someone else could take over links the old store printed on QR codes.
"""

import re
from typing import Literal

from utils.translit import to_ascii_latin

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 40
SLUG_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
_SLUG_RE = re.compile(SLUG_PATTERN)

RESERVED_SLUGS = frozenset(
    {
        "about", "account", "admin", "api", "app", "assets", "auth", "billing", "blog", "bot",
        "cdn", "dashboard", "dev", "docs", "files", "ftp", "help", "img", "images", "info",
        "javon", "login", "logout", "mail", "media", "my", "news", "ns1", "ns2", "panel",
        "pay", "payment", "register", "root", "shop", "signup", "smtp", "staging", "static",
        "status", "store", "support", "system", "telegram", "test", "www",
        "mini", "miniapp", "minio", "webhook", "webhooks",
    }
)  # fmt: skip

SlugProblem = Literal["invalid", "reserved"]

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Store name -> slug candidate. May return "" when nothing usable is left."""
    # "O'zbek" -> "ozbek" (not "o-zbek"), "Китоб" -> "kitob", "Café" -> "cafe".
    s = _NON_ALNUM.sub("-", to_ascii_latin(text)).strip("-")
    if s and not s[0].isalpha():
        s = f"kitob-{s}"  # "1000 kitob" -> "kitob-1000-kitob"
    return _trim(s)


def slug_problem(slug: str) -> SlugProblem | None:
    if not (SLUG_MIN_LENGTH <= len(slug) <= SLUG_MAX_LENGTH) or not _SLUG_RE.match(slug):
        return "invalid"
    if slug in RESERVED_SLUGS:
        return "reserved"
    return None


def slug_candidates(base: str) -> list[str]:
    """Alternatives to offer when `base` is taken, best first. Excludes `base` itself."""
    if not base:
        return []
    raw = [f"{base}-kitob", f"{base}-books", f"{base}-uz", *(f"{base}-{n}" for n in range(2, 10))]
    result: list[str] = []
    for candidate in raw:
        candidate = _trim(candidate)
        if candidate != base and candidate not in result and slug_problem(candidate) is None:
            result.append(candidate)
    return result


def _trim(slug: str) -> str:
    return slug[:SLUG_MAX_LENGTH].rstrip("-")
