"""
Telegram Login Widget verification
==================================
https://core.telegram.org/widgets/login#checking-authorization

The widget gives the browser a payload signed with the platform bot's token:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields) if k != "hash")
    secret_key        = SHA256(bot_token)
    hash              = hex(HMAC_SHA256(secret_key, data_check_string))

Every field except `hash` is signed, including ones we do not use (photo_url) and
ones Telegram may add later — so the caller passes the payload exactly as received.

Pure functions, no I/O: the clock is a parameter so tests can move it.
"""

import hashlib
import hmac
from collections.abc import Mapping
from enum import StrEnum


class TelegramAuthError(StrEnum):
    MISSING_HASH = "missing_hash"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"
    FROM_THE_FUTURE = "from_the_future"


# Clocks drift; a payload a few seconds "ahead" of us is fine.
_CLOCK_SKEW_S = 60


def _signature(payload: Mapping[str, object], bot_token: str) -> str:
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items()) if key != "hash" and value is not None
    )
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def verify_login_widget(
    payload: Mapping[str, object], bot_token: str, max_age_s: int, now: float
) -> TelegramAuthError | None:
    """None if the payload is genuine and fresh, otherwise the reason it is not."""
    received_hash = payload.get("hash")
    if not isinstance(received_hash, str) or not received_hash:
        return TelegramAuthError.MISSING_HASH
    if not hmac.compare_digest(_signature(payload, bot_token), received_hash.lower()):
        return TelegramAuthError.BAD_SIGNATURE

    try:
        auth_date = int(str(payload.get("auth_date")))
    except ValueError:
        return TelegramAuthError.BAD_SIGNATURE
    if auth_date > now + _CLOCK_SKEW_S:
        return TelegramAuthError.FROM_THE_FUTURE
    if now - auth_date > max_age_s:
        return TelegramAuthError.EXPIRED
    return None


def sign_login_widget(payload: Mapping[str, object], bot_token: str) -> str:
    """The hash Telegram would produce. For tests and local tooling only."""
    return _signature(payload, bot_token)
