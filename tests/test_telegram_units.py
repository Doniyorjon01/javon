"""Pure pieces of the Telegram integration: signatures, deep links, texts, money."""

import re
import time

import pytest

from services.telegram import url_button, web_app_button
from services.telegram_texts import TEXTS, pick_lang, raw, text
from utils.crypto import DecryptionError, decrypt, encrypt
from utils.i18n import Lang
from utils.money import format_som
from utils.signing import (
    group_link_code,
    order_start_code,
    parse_group_link_code,
    parse_order_start_code,
)
from utils.telegram_auth import MiniAppUser, TelegramAuthError, sign_init_data, verify_init_data

TOKEN = "123456:ABC-test-token-for-unit-tests-xyz0123456"
NOW = 1_800_000_000


def make(**overrides: str) -> str:
    fields = {
        "auth_date": str(NOW),
        "user": '{"id":42,"first_name":"Aziz","language_code":"ru"}',
        **overrides,
    }
    return sign_init_data(fields, TOKEN)


def test_init_data_accepted() -> None:
    assert verify_init_data(make(), TOKEN, 3600, NOW + 10) == MiniAppUser(42, "Aziz", "ru")


@pytest.mark.parametrize(
    ("data", "now", "problem"),
    [
        (make(), NOW + 7200, TelegramAuthError.EXPIRED),
        (make(), NOW - 3600, TelegramAuthError.FROM_THE_FUTURE),
        (make().replace("Aziz", "Hacker"), NOW, TelegramAuthError.BAD_SIGNATURE),
        (
            sign_init_data({"auth_date": str(NOW), "user": '{"id":42}'}, "999:other"),
            NOW,
            TelegramAuthError.BAD_SIGNATURE,
        ),
        ("auth_date=1&user=%7B%7D", NOW, TelegramAuthError.MISSING_HASH),
        ("%%%", NOW, TelegramAuthError.BAD_SIGNATURE),
    ],
)
def test_init_data_refused(data: str, now: int, problem: TelegramAuthError) -> None:
    assert verify_init_data(data, TOKEN, 3600, now) == problem


def test_deep_link_codes() -> None:
    code = group_link_code(7)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)
    assert parse_group_link_code(code) == 7
    assert parse_group_link_code(code.replace("g7_", "g8_")) is None
    assert parse_group_link_code("g7_forged") is None

    start = order_start_code(7, 1234)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", start)
    assert parse_order_start_code(7, start) == 1234
    assert parse_order_start_code(8, start) is None  # another store's bot
    assert parse_order_start_code(7, "o1234_nope") is None


def test_texts_have_every_language_and_the_same_placeholders() -> None:
    for key, by_lang in TEXTS.items():
        assert set(by_lang) == set(Lang), key
        fields = {lang: sorted(re.findall(r"\{(\w+)\}", template)) for lang, template in by_lang.items()}
        assert len({tuple(f) for f in fields.values()}) == 1, key


def test_values_are_escaped_unless_raw() -> None:
    message = text("buyer_status_accepted", Lang.uz, number="<b>1</b>")
    assert "&lt;b&gt;1&lt;/b&gt;" in message
    assert "<i>x</i>" in text("buyer_status_cancelled", Lang.en, number=1, reason=raw("<i>x</i>"))


def test_pick_lang() -> None:
    assert pick_lang("ru", Lang.uz) == Lang.ru
    assert pick_lang("en-US", Lang.uz) == Lang.en
    assert pick_lang("de", Lang.uz) == Lang.uz
    assert pick_lang(None, Lang.ru) == Lang.ru


def test_buttons_need_https() -> None:
    assert url_button("x", "http://localhost:3000/a") is None
    assert url_button("x", "https://localhost/a") is None
    assert url_button("x", "https://javon.uz/a") == {"text": "x", "url": "https://javon.uz/a"}
    assert web_app_button("x", "http://varaq.javon.uz") is None


@pytest.mark.parametrize(
    ("tiyin", "lang", "expected"),
    [
        (12_050_000, Lang.uz, "120 500 so'm"),
        (12_050_050, Lang.ru, "120 500,50 сум"),
        (5_000, Lang.en, "50 UZS"),
        (0, Lang.uz, "0 so'm"),
    ],
)
def test_format_som(tiyin: int, lang: Lang, expected: str) -> None:
    assert format_som(tiyin, lang) == expected


def test_token_encryption_round_trip() -> None:
    sealed = encrypt("123:secret")
    assert b"secret" not in sealed
    assert decrypt(sealed) == "123:secret"
    with pytest.raises(DecryptionError):
        decrypt(b"not a fernet token")


def test_init_data_clock_is_a_parameter() -> None:
    assert isinstance(verify_init_data(make(), TOKEN, 3600, time.time()), TelegramAuthError)
