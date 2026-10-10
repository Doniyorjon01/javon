import pytest

from utils.i18n import DEFAULT_LANG, Lang, parse_accept_language


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, DEFAULT_LANG),
        ("", DEFAULT_LANG),
        ("ru", Lang.ru),
        ("en-US,en;q=0.9", Lang.en),
        ("uz-Latn-UZ", Lang.uz),
        ("fr-FR, ru;q=0.5", Lang.ru),  # unsupported first choice is skipped
        ("ru;q=0.1, en;q=0.9", Lang.en),  # q-value wins over position
        ("ru, en", Lang.ru),  # equal q keeps header order
        ("ru;q=0, en;q=0.5", Lang.en),  # q=0 means "not acceptable"
        ("ru;q=abc, en;q=0.5", Lang.en),  # malformed q is treated as 0
        ("de, fr", DEFAULT_LANG),
        (" , ;q=1", DEFAULT_LANG),
    ],
)
def test_parse_accept_language(header: str | None, expected: Lang) -> None:
    assert parse_accept_language(header) == expected
