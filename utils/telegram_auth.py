"""
Telegram sign-in verification
=============================
Two signed payloads come from Telegram: the Login Widget (owners and staff
signing in to the admin panel) and Mini App initData (buyers inside a store's
Telegram Mini App; bottom of this file).

Login Widget
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
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode


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


# --------------------------------------------------------------------------- #
# Mini App (Web App) initData
# --------------------------------------------------------------------------- #
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# The Mini App sends `Telegram.WebApp.initData`, a query string signed with the
# STORE'S bot token:
#     data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields) if k != "hash")
#     secret_key        = HMAC_SHA256(key="WebAppData", msg=bot_token)
#     hash              = hex(HMAC_SHA256(secret_key, data_check_string))
@dataclass(frozen=True, slots=True)
class MiniAppUser:
    id: int
    first_name: str
    language_code: str | None


def _init_data_signature(fields: Mapping[str, str], bot_token: str) -> str:
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()) if key != "hash")
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def verify_init_data(
    init_data: str, bot_token: str, max_age_s: int, now: float
) -> MiniAppUser | TelegramAuthError:
    """The signed-in Telegram user, or the reason the data is not acceptable."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return TelegramAuthError.BAD_SIGNATURE
    received_hash = fields.get("hash")
    if not received_hash:
        return TelegramAuthError.MISSING_HASH
    if not hmac.compare_digest(_init_data_signature(fields, bot_token), received_hash.lower()):
        return TelegramAuthError.BAD_SIGNATURE
    try:
        auth_date = int(fields.get("auth_date", ""))
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (ValueError, KeyError, TypeError):
        return TelegramAuthError.BAD_SIGNATURE
    if auth_date > now + _CLOCK_SKEW_S:
        return TelegramAuthError.FROM_THE_FUTURE
    if now - auth_date > max_age_s:
        return TelegramAuthError.EXPIRED
    return MiniAppUser(
        id=user_id, first_name=str(user.get("first_name", ""))[:80], language_code=user.get("language_code")
    )


def sign_init_data(fields: Mapping[str, str], bot_token: str) -> str:
    """A complete initData string as Telegram would build it. For tests only."""
    signed = {**fields, "hash": _init_data_signature(fields, bot_token)}
    return urlencode(signed)
