import pytest
from pydantic import ValidationError

from schemas.catalog import BookCreate, BookUpdate


def _book(**overrides: object) -> dict:
    return {"title": "O'tkan kunlar", "authors": ["Abdulla Qodiriy"], **overrides}


def test_isbn_is_normalized_to_isbn13() -> None:
    assert BookCreate(**_book(isbn="0-306-40615-2")).isbn == "9780306406157"


def test_empty_isbn_means_no_isbn() -> None:
    assert BookCreate(**_book(isbn="  ")).isbn is None


def test_invalid_isbn_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ISBN"):
        BookCreate(**_book(isbn="9780306406158"))


@pytest.mark.parametrize("field", ["status", "created_by_tenant_id", "search_text", "id", "cover_key"])
def test_server_owned_fields_are_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        BookCreate(**_book(**{field: "x"}))


@pytest.mark.parametrize(
    "authors",
    [
        [],  # at least one
        ["***"],  # nothing searchable
        ["Abdulla Qodiriy", "Абдулла Қодирий"],  # same person twice, two scripts
        [f"Author {i}" for i in range(11)],  # too many
    ],
)
def test_bad_author_lists(authors: list[str]) -> None:
    with pytest.raises(ValidationError):
        BookCreate(**_book(authors=authors))


@pytest.mark.parametrize(
    "field_value",
    [
        {"published_year": 1200},
        {"pages": 0},
        {"mxik_code": "12345"},  # MXIK has 17 digits
        {"title": "   "},
        {"language": "de"},
    ],
)
def test_out_of_range_values(field_value: dict) -> None:
    with pytest.raises(ValidationError):
        BookCreate(**_book(**field_value))


def test_valid_mxik_code() -> None:
    assert BookCreate(**_book(mxik_code="04901001001000000")).mxik_code == "04901001001000000"


def test_update_sends_only_what_changed() -> None:
    data = BookUpdate(pages=320, publisher="")
    assert data.model_dump(exclude_unset=True) == {"pages": 320, "publisher": None}
