import string

import pytest

from errors import generate_error
from translations import MESSAGES, Msg
from utils.i18n import Lang


def _placeholders(text: str) -> int:
    return sum(1 for _, field, _, _ in string.Formatter().parse(text) if field is not None)


@pytest.mark.parametrize("msg", list(Msg))
def test_every_message_has_every_language(msg: Msg) -> None:
    texts = MESSAGES.get(msg)
    assert texts is not None, f"{msg} has no translations"
    for lang in Lang:
        assert texts.get(lang), f"{msg} is missing {lang}"


@pytest.mark.parametrize("msg", list(Msg))
def test_placeholder_count_matches_across_languages(msg: Msg) -> None:
    counts = {lang: _placeholders(MESSAGES[msg][lang]) for lang in Lang}
    assert len(set(counts.values())) == 1, f"{msg}: {counts}"


def test_message_codes_are_unique() -> None:
    values = [m.value for m in Msg]
    assert len(values) == len(set(values))


def test_generate_error_formats_values_not_the_tuple() -> None:
    exc = generate_error(Msg.UNKNOWN_ERROR, Lang.en, format_values=("disk full",))
    assert exc.status_code == 400
    assert exc.detail == {"code": "unknown_error", "message": "Unknown error: disk full"}
