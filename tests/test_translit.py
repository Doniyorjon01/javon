import pytest

from utils.translit import book_dedupe_key, detect_script, search_key


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("O'tkan kunlar",), "otkan kunlar"),
        (("Oʻtkan kunlar",), "otkan kunlar"),  # official Uzbek apostrophe
        (("Ўтган кунлар",), "otgan kunlar"),
        (("Абдулла Қодирий",), "abdulla qodiriy"),
        (("Достоевский", "Преступление и наказание"), "dostoevskiy prestuplenie i nakazanie"),
        (("  Kitob — uyi!  ", None, "Café"), "kitob uyi cafe"),
        (("Garri Potter 2",), "garri potter 2"),
        (("***",), ""),
        ((None,), ""),
    ],
)
def test_search_key(parts: tuple, expected: str) -> None:
    assert search_key(*parts) == expected


def test_latin_and_cyrillic_spellings_of_a_name_match() -> None:
    assert search_key("Abdulla Qodiriy") == search_key("Абдулла Қодирий")
    assert search_key("Gʻafur Gʻulom") == search_key("Ғафур Ғулом")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("O'tkan kunlar", "latn"),
        ("Ўтган кунлар", "cyrl"),
        ("Преступление и наказание", "cyrl"),
        ("Harry Potter va falsafa toshi", "latn"),
        ("1984", "other"),
        ("", "other"),
        ("Python: Изучаем программирование", "cyrl"),  # majority wins
    ],
)
def test_detect_script(text: str, expected: str) -> None:
    assert detect_script(text) == expected


def test_book_dedupe_key_ignores_spelling_and_author_order() -> None:
    def key(**overrides: object) -> str:
        fields: dict = {
            "language": "uz",
            "script": "latn",
            "title": "O'tkan kunlar",
            "subtitle": None,
            "authors": ["Abdulla Qodiriy", "Ikkinchi Muallif"],
            "publisher": "Sharq",
        }
        return book_dedupe_key(**{**fields, **overrides})

    assert key() == key(title="O‘TKAN  kunlar", authors=["Ikkinchi Muallif", "Abdulla Qodiriy"])
    assert key() != key(script="cyrl")
    assert key() != key(publisher="Yangi asr")
    assert key() != key(publisher=None)
    assert key() != key(subtitle="1-jild")
    assert key() != key(language="ru")
