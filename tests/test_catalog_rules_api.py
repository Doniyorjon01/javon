"""
Catalog rules for store submissions: the pending quota, duplicates without an
ISBN, rejection with a reason, the store's submissions list, script and
package code.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_catalog
from models import BookStatus, Tenant, User
from schemas.catalog import BookCreate
from tests.factories import make_tenant, make_user, sign_in

pytestmark = pytest.mark.db

SARIQ_DEV = {"title": "Sariq devni minib", "authors": ["Xudoyberdi To'xtaboyev"], "publisher": "Yangi asr"}


async def store_with_owner(db: AsyncSession, slug: str) -> tuple[Tenant, User]:
    owner = await make_user(db, f"Owner {slug}")
    return await make_tenant(db, slug, owner), owner


async def add_book(client: AsyncClient, tenant: Tenant, **fields: object) -> dict:
    resp = await client.post(f"/tenants/{tenant.id}/catalog/books", json=fields)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Pending quota
# --------------------------------------------------------------------------- #
async def test_pending_quota_per_store(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAX_PENDING_BOOKS_PER_STORE", 2)
    store, owner = await store_with_owner(db, "varaq")
    other, other_owner = await store_with_owner(db, "boshqa")
    admin = await make_user(db, "Admin", is_platform_admin=True)

    await sign_in(client, owner)
    first = await add_book(client, store, title="Birinchi", authors=["Muallif Bir"])
    await add_book(client, store, title="Ikkinchi", authors=["Muallif Bir"])
    third = await client.post(
        f"/tenants/{store.id}/catalog/books", json={"title": "Uchinchi", "authors": ["M B"]}
    )
    assert third.status_code == 409
    assert third.json()["detail"]["code"] == "pending_books_limit"

    # Another store has its own quota.
    await sign_in(client, other_owner)
    await add_book(client, other, title="Boshqa kitob", authors=["Muallif Ikki"])

    # Once one is reviewed, there is room again.
    await sign_in(client, admin)
    assert (await client.post(f"/system/catalog/books/{first['id']}/approve")).status_code == 200
    await sign_in(client, owner)
    await add_book(client, store, title="Uchinchi", authors=["Muallif Bir"])


async def test_platform_import_has_no_quota(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_PENDING_BOOKS_PER_STORE", 1)
    for i in range(3):
        await db_catalog.create_book(db, BookCreate(title=f"Kitob {i}", authors=["Muallif"]), tenant_id=None)


# --------------------------------------------------------------------------- #
# Duplicates without ISBN
# --------------------------------------------------------------------------- #
async def test_isbn_less_duplicate_points_to_the_existing_book(client: AsyncClient, db: AsyncSession) -> None:
    existing = await db_catalog.create_book(
        db, BookCreate(**SARIQ_DEV), tenant_id=None, book_status=BookStatus.APPROVED
    )
    store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)

    # Different apostrophe, letter case and extra spaces: still the same book.
    same = {**SARIQ_DEV, "title": "SARIQ  devni minib", "authors": ["Xudoyberdi Toʻxtaboyev"]}
    resp = await client.post(f"/tenants/{store.id}/catalog/books", json=same)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "book_duplicate"
    assert resp.json()["detail"]["book_id"] == existing.id

    # The Cyrillic edition and another publisher's edition are different products.
    cyrillic = {**SARIQ_DEV, "title": "Сариқ девни миниб", "authors": ["Худойберди Тўхтабоев"]}
    assert (await add_book(client, store, **cyrillic))["script"] == "cyrl"
    await add_book(client, store, **{**SARIQ_DEV, "publisher": "Sharq"})


async def test_own_pending_duplicate_is_caught_other_stores_pending_is_not(
    client: AsyncClient, db: AsyncSession
) -> None:
    store, owner = await store_with_owner(db, "varaq")
    other, other_owner = await store_with_owner(db, "boshqa")

    await sign_in(client, owner)
    mine = await add_book(client, store, **SARIQ_DEV)
    again = await client.post(f"/tenants/{store.id}/catalog/books", json=SARIQ_DEV)
    assert again.status_code == 409
    assert again.json()["detail"]["book_id"] == mine["id"]

    # The other store cannot see our pending book, so it must not be told its id.
    await sign_in(client, other_owner)
    await add_book(client, other, **SARIQ_DEV)


# --------------------------------------------------------------------------- #
# Rejection, reason and the submissions list
# --------------------------------------------------------------------------- #
async def test_rejected_book_shows_its_reason_only_to_the_submitting_store(
    client: AsyncClient, db: AsyncSession
) -> None:
    store, owner = await store_with_owner(db, "varaq")
    other, other_owner = await store_with_owner(db, "boshqa")
    admin = await make_user(db, "Admin", is_platform_admin=True)

    await sign_in(client, owner)
    book = await add_book(client, store, title="Xato kitob", authors=["Kimdir Bir"])

    await sign_in(client, admin)
    no_reason = await client.post(f"/system/catalog/books/{book['id']}/reject")
    assert no_reason.status_code == 422
    rejected = await client.post(
        f"/system/catalog/books/{book['id']}/reject", json={"reason": "Sarlavha noto'g'ri yozilgan"}
    )
    assert rejected.json()["review_note"] == "Sarlavha noto'g'ri yozilgan"

    await sign_in(client, owner)
    mine = await client.get(f"/tenants/{store.id}/catalog/books/{book['id']}")
    assert mine.status_code == 200
    assert (mine.json()["status"], mine.json()["review_note"]) == ("rejected", "Sarlavha noto'g'ri yozilgan")
    search = await client.get(f"/tenants/{store.id}/catalog/books", params={"q": "xato kitob"})
    assert search.json()["items"] == []

    submissions = await client.get(f"/tenants/{store.id}/catalog/submissions", params={"status": "rejected"})
    assert [b["id"] for b in submissions.json()["items"]] == [book["id"]]
    pending = await client.get(f"/tenants/{store.id}/catalog/submissions", params={"status": "pending"})
    assert pending.json()["items"] == []

    await sign_in(client, other_owner)
    assert (await client.get(f"/tenants/{other.id}/catalog/books/{book['id']}")).status_code == 404
    assert (await client.get(f"/tenants/{other.id}/catalog/submissions")).json()["items"] == []

    # Approving later clears the note.
    await sign_in(client, admin)
    approved = await client.post(f"/system/catalog/books/{book['id']}/approve")
    assert (approved.json()["status"], approved.json()["review_note"]) == ("approved", None)


async def test_submissions_are_newest_first(client: AsyncClient, db: AsyncSession) -> None:
    store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    first = await add_book(client, store, title="Birinchi", authors=["Muallif Bir"])
    second = await add_book(client, store, title="Ikkinchi", authors=["Muallif Bir"])
    items = (await client.get(f"/tenants/{store.id}/catalog/submissions")).json()["items"]
    assert [b["id"] for b in items] == [second["id"], first["id"]]


# --------------------------------------------------------------------------- #
# Script and package code
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("title", "script", "expected"),
    [
        ("O'tkan kunlar", None, "latn"),
        ("Ўтган кунлар", None, "cyrl"),
        ("1984", None, "other"),
        ("1984", "latn", "latn"),  # the store knows better than the title
    ],
)
async def test_script_is_detected_unless_given(
    client: AsyncClient, db: AsyncSession, title: str, script: str | None, expected: str
) -> None:
    store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    fields: dict[str, object] = {"title": title, "authors": ["Muallif Bir"]}
    if script:
        fields["script"] = script
    assert (await add_book(client, store, **fields))["script"] == expected


async def test_package_code_is_digits_only(client: AsyncClient, db: AsyncSession) -> None:
    store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    url = f"/tenants/{store.id}/catalog/books"
    for bad in ("abc", "12-34", "1" * 21):
        resp = await client.post(url, json={"title": "Kitob", "authors": ["M B"], "package_code": bad})
        assert resp.status_code == 422, bad
    book = await add_book(client, store, title="Kitob", authors=["M B"], package_code=" 1500123 ")
    assert book["package_code"] == "1500123"
