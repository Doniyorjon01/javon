import pytest

from utils.slug import SLUG_MAX_LENGTH, slug_candidates, slug_problem, slugify


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Varaq", "varaq"),
        ("Kitob olami", "kitob-olami"),
        ("Китоб олами", "kitob-olami"),
        ("O\u02bbzbekiston kitoblari", "ozbekiston-kitoblari"),  # U+02BB, as in official Uzbek Latin
        ("O'zbek kitob", "ozbek-kitob"),  # plain ASCII apostrophe
        ("Ғунча", "guncha"),
        ("Қалб ва ҳис", "qalb-va-his"),
        ("Book & Café", "book-cafe"),
        ("  Kitob — uyi!  ", "kitob-uyi"),
        ("1000 kitob", "kitob-1000-kitob"),  # must start with a letter
        ("***", ""),
        ("书店", ""),  # nothing transliterable left
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_slugify_respects_max_length_without_trailing_hyphen() -> None:
    slug = slugify("juda " * 20)
    assert len(slug) <= SLUG_MAX_LENGTH
    assert not slug.endswith("-")


@pytest.mark.parametrize(
    ("slug", "problem"),
    [
        ("varaq", None),
        ("kitob-olami-2", None),
        ("ab", "invalid"),  # too short
        ("a" * 41, "invalid"),  # too long
        ("Varaq", "invalid"),  # uppercase
        ("kitob--olami", "invalid"),
        ("-kitob", "invalid"),
        ("kitob-", "invalid"),
        ("2kitob", "invalid"),
        ("kitob_olami", "invalid"),
        ("www", "reserved"),
        ("admin", "reserved"),
    ],
)
def test_slug_problem(slug: str, problem: str | None) -> None:
    assert slug_problem(slug) == problem


def test_slug_candidates_are_valid_unique_and_exclude_base() -> None:
    candidates = slug_candidates("varaq")
    assert "varaq" not in candidates
    assert len(candidates) == len(set(candidates))
    assert all(slug_problem(c) is None for c in candidates)
    assert candidates[:2] == ["varaq-kitob", "varaq-books"]


def test_slug_candidates_for_long_base_stay_within_limit() -> None:
    base = "a" * SLUG_MAX_LENGTH
    assert all(len(c) <= SLUG_MAX_LENGTH for c in slug_candidates(base))


def test_slug_candidates_for_empty_base() -> None:
    assert slug_candidates("") == []