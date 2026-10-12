import pytest

from utils.translit import search_key


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
