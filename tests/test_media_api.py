"""Logo and cover uploads through the API (MemoryStorage instead of MinIO)."""

import io

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from models import MemberRole
from services.storage import MemoryStorage
from tests.factories import add_member, make_book, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


def jpeg(size: tuple[int, int] = (600, 900)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "teal").save(out, format="JPEG")
    return out.getvalue()


def upload(data: bytes, name: str = "photo.jpg", content_type: str = "image/jpeg") -> dict:
    return {"file": (name, data, content_type)}


async def test_owner_uploads_replaces_and_deletes_the_logo(
    client: AsyncClient, db: AsyncSession, storage: MemoryStorage
) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)

    first = await client.put(f"/tenants/{tenant.id}/logo", files=upload(jpeg((512, 512))))
    assert first.status_code == 200, first.text
    logo = first.json()["logo"]
    assert set(logo) == {"s", "l"}
    assert logo["s"].startswith("http://media.test/javon-media/logos/")
    first_keys = set(storage.objects)
    assert len(first_keys) == 2
    assert all(content_type == "image/webp" for _, content_type in storage.objects.values())

    second = await client.put(f"/tenants/{tenant.id}/logo", files=upload(jpeg((400, 400))))
    assert second.json()["logo"] != logo
    assert not first_keys & set(storage.objects)  # the old files are gone
    assert len(storage.objects) == 2

    # The public storefront shows it too.
    assert (await client.get("/storefront/varaq")).json()["logo"] == second.json()["logo"]

    deleted = await client.delete(f"/tenants/{tenant.id}/logo")
    assert deleted.json()["logo"] is None
    assert storage.objects == {}


async def test_logo_is_the_owners_business(client: AsyncClient, db: AsyncSession) -> None:
    staff = await make_user(db)
    tenant = await make_tenant(db, "varaq")
    await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    assert (await client.put(f"/tenants/{tenant.id}/logo", files=upload(jpeg()))).status_code == 403


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"MZ\x90\x00 definitely an exe", "not_an_image"),
        (jpeg((60, 60)), "too_small"),
    ],
)
async def test_bad_pictures_are_refused(
    client: AsyncClient, db: AsyncSession, data: bytes, reason: str
) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    resp = await client.put(f"/tenants/{tenant.id}/logo", files=upload(data))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "image_invalid"
    assert resp.json()["detail"]["reason"] == reason


async def test_upload_size_limit_and_empty_file(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    too_big = await client.put(f"/tenants/{tenant.id}/logo", files=upload(b"x" * (5 * 1024 * 1024 + 10)))
    assert too_big.status_code == 413
    empty = await client.put(f"/tenants/{tenant.id}/logo", files=upload(b""))
    assert empty.json()["detail"]["code"] == "file_empty"


async def test_without_storage_uploads_answer_503(
    app: FastAPI, client: AsyncClient, db: AsyncSession
) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    app.state.storage = None
    resp = await client.put(f"/tenants/{tenant.id}/logo", files=upload(jpeg()))
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "storage_unavailable"


async def test_cover_rules(client: AsyncClient, db: AsyncSession, storage: MemoryStorage) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    other_owner = await make_user(db)
    other = await make_tenant(db, "boshqa", other_owner)
    admin = await make_user(db, "Admin", is_platform_admin=True)
    approved = await make_book(db, "Tasdiqlangan")

    await sign_in(client, owner)
    pending = (
        await client.post(
            f"/tenants/{tenant.id}/catalog/books", json={"title": "Yangi", "authors": ["Kimdir Bir"]}
        )
    ).json()
    ok = await client.put(f"/tenants/{tenant.id}/catalog/books/{pending['id']}/cover", files=upload(jpeg()))
    assert ok.status_code == 200, ok.text
    assert set(ok.json()["cover"]) == {"s", "m", "l"}
    assert len(storage.objects) == 3

    # An approved book's cover is shared by every store: only the platform admin changes it.
    refused = await client.put(
        f"/tenants/{tenant.id}/catalog/books/{approved.id}/cover", files=upload(jpeg())
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "cover_not_allowed"

    # Another store sees the pending book (shared catalog) but may not change its cover.
    await sign_in(client, other_owner)
    foreign = await client.put(
        f"/tenants/{other.id}/catalog/books/{pending['id']}/cover", files=upload(jpeg())
    )
    assert foreign.status_code == 403
    assert foreign.json()["detail"]["code"] == "cover_not_allowed"

    await sign_in(client, admin)
    by_admin = await client.put(f"/system/catalog/books/{approved.id}/cover", files=upload(jpeg()))
    assert by_admin.status_code == 200
    assert len(storage.objects) == 6
    removed = await client.delete(f"/system/catalog/books/{approved.id}/cover")
    assert removed.json()["cover"] is None
    assert len(storage.objects) == 3
