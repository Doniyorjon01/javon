"""
Catalog through the HTTP API: search, barcode lookup, a store's own submissions,
and who sees what before and after moderation.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_catalog
from models import Author, BookStatus, MemberRole, Tenant, User
from schemas.catalog import BookCreate
from tests.factories import add_member, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db

OTKAN_KUNLAR = {
    "isbn": "978-0-306-40615-7",
    "title": "O'tkan kunlar",
    "authors": ["Abdulla Qodiriy"],
    "publisher": "Sharq",
    "language": "uz",
    "published_year": 2019,
}
DOSTOEVSKIY = {
    "title": "Преступление и наказание",
    "authors": ["Фёдор Достоевский"],
    "language": "ru",
}


async def approved_book(db: AsyncSession, **fields: object) -> int:
    book = await db_catalog.create_book(
        db, BookCreate(**fields), tenant_id=None, book_status=BookStatus.APPROVED
    )
    return book.id


async def store_with_owner(db: AsyncSession, slug: str) -> tuple[Tenant, User]:
    owner = await make_user(db, f"Owner {slug}")
    return await make_tenant(db, slug, owner), owner


async def search(client: AsyncClient, tenant: Tenant, q: str) -> list[str]:
    resp = await client.get(f"/tenants/{tenant.id}/catalog/books", params={"q": q})
    assert resp.status_code == 200, resp.text
    return [item["title"] for item in resp.json()["items"]]


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("Қодирий", ["O'tkan kunlar"]),  # Cyrillic query, Latin book
        ("o'tkan", ["O'tkan kunlar"]),
        ("kunlar", ["O'tkan kunlar"]),
        ("sharq", ["O'tkan kunlar"]),  # publisher
        ("dostoevskiy", ["Преступление и наказание"]),  # Latin query, Cyrillic book
        ("dostoevsky", ["Преступление и наказание"]),  # typo
        ("наказание", ["Преступление и наказание"]),
        ("0-306-40615-2", ["O'tkan kunlar"]),  # ISBN-10 of the stored ISBN-13
        ("garri potter", []),
    ],
)
async def test_search(client: AsyncClient, db: AsyncSession, q: str, expected: list[str]) -> None:
    await approved_book(db, **OTKAN_KUNLAR)
    await approved_book(db, **DOSTOEVSKIY)
    tenant, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    assert await search(client, tenant, q) == expected


async def test_search_result_shape_and_pagination(client: AsyncClient, db: AsyncSession) -> None:
    for n in range(1, 4):
        await approved_book(db, title=f"Kitob {n}", authors=["Muallif"])
    tenant, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)

    resp = await client.get(f"/tenants/{tenant.id}/catalog/books", params={"q": "muallif", "size": 2})
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    first = body["items"][0]
    assert first["authors"] == [{"id": first["authors"][0]["id"], "name": "Muallif"}]
    assert first["status"] == "approved"


async def test_too_short_query(client: AsyncClient, db: AsyncSession) -> None:
    tenant, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    resp = await client.get(f"/tenants/{tenant.id}/catalog/books", params={"q": "a!"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "search_query_too_short"


# --------------------------------------------------------------------------- #
# Barcode scanner
# --------------------------------------------------------------------------- #
async def test_isbn_lookup(client: AsyncClient, db: AsyncSession) -> None:
    await approved_book(db, **OTKAN_KUNLAR)
    tenant, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    base = f"/tenants/{tenant.id}/catalog/isbn"

    found = await client.get(f"{base}/9780306406157")
    assert found.status_code == 200
    assert found.json()["title"] == "O'tkan kunlar"
    assert found.json()["publisher"]["name"] == "Sharq"

    missing = await client.get(f"{base}/9789943000001")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "book_isbn_not_found"

    invalid = await client.get(f"{base}/9780306406158")
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_isbn"


# --------------------------------------------------------------------------- #
# A store's own submissions
# --------------------------------------------------------------------------- #
async def test_submitted_book_is_private_until_approved(client: AsyncClient, db: AsyncSession) -> None:
    store_a, owner_a = await store_with_owner(db, "varaq")
    store_b, owner_b = await store_with_owner(db, "kitobxon")
    admin = await make_user(db, "Admin", is_platform_admin=True)

    await sign_in(client, owner_a)
    resp = await client.post(f"/tenants/{store_a.id}/catalog/books", json=OTKAN_KUNLAR)
    assert resp.status_code == 201, resp.text
    book = resp.json()
    assert book["status"] == "pending"
    assert book["isbn13"] == "9780306406157"
    # The submitting store can use it right away.
    assert await search(client, store_a, "qodiriy") == ["O'tkan kunlar"]
    assert (await client.get(f"/tenants/{store_a.id}/catalog/books/{book['id']}")).status_code == 200

    # Another store cannot see it, by any route.
    await sign_in(client, owner_b)
    assert await search(client, store_b, "qodiriy") == []
    assert (await client.get(f"/tenants/{store_b.id}/catalog/books/{book['id']}")).status_code == 404
    assert (await client.get(f"/tenants/{store_b.id}/catalog/isbn/9780306406157")).status_code == 404

    await sign_in(client, admin)
    approved = await client.post(f"/system/catalog/books/{book['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    await sign_in(client, owner_b)
    assert await search(client, store_b, "qodiriy") == ["O'tkan kunlar"]


async def test_duplicate_isbn_and_rejection_frees_it(client: AsyncClient, db: AsyncSession) -> None:
    store, owner = await store_with_owner(db, "varaq")
    admin = await make_user(db, "Admin", is_platform_admin=True)
    await sign_in(client, owner)
    first = (await client.post(f"/tenants/{store.id}/catalog/books", json=OTKAN_KUNLAR)).json()

    duplicate = await client.post(f"/tenants/{store.id}/catalog/books", json=OTKAN_KUNLAR)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "book_isbn_exists"

    await sign_in(client, admin)
    assert (await client.post(f"/system/catalog/books/{first['id']}/reject")).json()["status"] == "rejected"

    await sign_in(client, owner)
    again = await client.post(f"/tenants/{store.id}/catalog/books", json=OTKAN_KUNLAR)
    assert again.status_code == 201
    # The rejected record is hidden; only the new one is found.
    assert [
        b["id"]
        for b in (
            await client.get(f"/tenants/{store.id}/catalog/books", params={"q": "9780306406157"})
        ).json()["items"]
    ] == [again.json()["id"]]


async def test_staff_can_submit_outsiders_cannot(client: AsyncClient, db: AsyncSession) -> None:
    store, _owner = await store_with_owner(db, "varaq")
    staff = await make_user(db, "Staff")
    await add_member(db, store, staff, MemberRole.STAFF)
    outsider = await make_user(db, "Outsider")

    await sign_in(client, staff)
    resp = await client.post(f"/tenants/{store.id}/catalog/books", json=DOSTOEVSKIY)
    assert resp.status_code == 201

    await sign_in(client, outsider)
    resp = await client.post(f"/tenants/{store.id}/catalog/books", json=DOSTOEVSKIY)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "store_not_found"


async def test_client_cannot_self_approve(client: AsyncClient, db: AsyncSession) -> None:
    store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    resp = await client.post(f"/tenants/{store.id}/catalog/books", json={**DOSTOEVSKIY, "status": "approved"})
    assert resp.status_code == 422


async def test_one_author_across_scripts(db: AsyncSession) -> None:
    await approved_book(db, title="O'tkan kunlar", authors=["Abdulla Qodiriy"])
    await approved_book(db, title="Меҳробдан чаён", authors=["Абдулла Қодирий"])
    authors = list(await db.scalars(select(Author)))
    assert [a.name for a in authors] == ["Abdulla Qodiriy"]


# --------------------------------------------------------------------------- #
# Moderation
# --------------------------------------------------------------------------- #
async def test_moderation_needs_platform_admin(client: AsyncClient, db: AsyncSession) -> None:
    _store, owner = await store_with_owner(db, "varaq")
    await sign_in(client, owner)
    resp = await client.get("/system/catalog/books")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "forbidden"


async def test_moderation_queue_and_correction(client: AsyncClient, db: AsyncSession) -> None:
    store, owner = await store_with_owner(db, "varaq")
    admin = await make_user(db, "Admin", is_platform_admin=True)
    await sign_in(client, owner)
    older = (await client.post(f"/tenants/{store.id}/catalog/books", json=DOSTOEVSKIY)).json()
    newer = (
        await client.post(
            f"/tenants/{store.id}/catalog/books",
            json={"title": "Otkan kunlr", "authors": ["Nomalum Yozuvchi"]},
        )
    ).json()

    await sign_in(client, admin)
    queue = (await client.get("/system/catalog/books", params={"status": "pending"})).json()
    assert [b["id"] for b in queue["items"]] == [older["id"], newer["id"]]

    fixed = await client.patch(
        f"/system/catalog/books/{newer['id']}",
        json={"title": "O'tkan kunlar", "authors": ["Abdulla Qodiriy"], "pages": 432},
    )
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert body["title"] == "O'tkan kunlar"
    assert [a["name"] for a in body["authors"]] == ["Abdulla Qodiriy"]
    assert body["pages"] == 432

    # search_text follows the correction: the new author is found, the replaced one is not.
    await sign_in(client, owner)
    assert await search(client, store, "Абдулла Қодирий") == ["O'tkan kunlar"]
    assert await search(client, store, "nomalum yozuvchi") == []
