"""
Telegram Login Widget signature check.

The reference vector below is computed independently of utils.telegram_auth
(plain hashlib/hmac, following Telegram's documented algorithm), so a mistake
shared by sign_login_widget and verify_login_widget would still be caught.
"""

import hashlib
import hmac

from utils.telegram_auth import TelegramAuthError, sign_login_widget, verify_login_widget

BOT_TOKEN = "123456:ABC-reference"
NOW = 1_760_000_000
PAYLOAD = {
    "id": 4242,
    "first_name": "Doniyor",
    "username": "doniyor_test",
    "photo_url": "https://t.me/i/userpic/320/x.jpg",
    "auth_date": NOW - 30,
}


def _reference_hash(payload: dict, bot_token: str) -> str:
    check = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def _signed(payload: dict) -> dict:
    return {**payload, "hash": _reference_hash(payload, BOT_TOKEN)}


def _verify(payload: dict, now: float = NOW) -> TelegramAuthError | None:
    return verify_login_widget(payload, BOT_TOKEN, max_age_s=86_400, now=now)


def test_sign_matches_reference() -> None:
    assert sign_login_widget(PAYLOAD, BOT_TOKEN) == _reference_hash(PAYLOAD, BOT_TOKEN)


def test_genuine_payload_passes() -> None:
    assert _verify(_signed(PAYLOAD)) is None


def test_uppercase_hash_passes() -> None:
    payload = _signed(PAYLOAD)
    payload["hash"] = payload["hash"].upper()
    assert _verify(payload) is None


def test_changed_field_fails() -> None:
    payload = _signed(PAYLOAD)
    payload["id"] = 1  # pretend to be someone else
    assert _verify(payload) == TelegramAuthError.BAD_SIGNATURE


def test_dropped_field_fails() -> None:
    payload = _signed(PAYLOAD)
    del payload["photo_url"]
    assert _verify(payload) == TelegramAuthError.BAD_SIGNATURE


def test_other_bot_token_fails() -> None:
    payload = {**PAYLOAD, "hash": _reference_hash(PAYLOAD, "999:another-bot")}
    assert _verify(payload) == TelegramAuthError.BAD_SIGNATURE


def test_missing_hash_fails() -> None:
    assert _verify(dict(PAYLOAD)) == TelegramAuthError.MISSING_HASH


def test_old_payload_is_expired() -> None:
    assert _verify(_signed(PAYLOAD), now=NOW + 86_400) == TelegramAuthError.EXPIRED


def test_payload_from_the_future_fails() -> None:
    assert _verify(_signed(PAYLOAD), now=NOW - 3_600) == TelegramAuthError.FROM_THE_FUTURE
