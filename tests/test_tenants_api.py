import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models import TenantStatus
from tests.factories import make_tenant

pytestmark = pytest.mark.db


async def test_slug_check_from_store_name(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/tenants/slug-check", params={"name": "Kitob olami"})
    assert resp.status_code == 200
    assert resp.json() == {"slug": "kitob-olami", "available": True, "reason": None, "suggestions": []}


async def test_slug_check_taken(client: AsyncClient, db: AsyncSession) -> None:
    await make_tenant(db, "varaq")
    body = (await client.get("/tenants/slug-check", params={"slug": "Varaq"})).json()
    assert body["slug"] == "varaq"
    assert body["available"] is False
    assert body["reason"] == "taken"
    assert body["suggestions"][0] == "varaq-kitob"


async def test_slug_check_needs_input(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/tenants/slug-check", params={"name": "***"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "slug_check_empty"


async def test_storefront_shows_public_fields_only(client: AsyncClient, db: AsyncSession) -> None:
    await make_tenant(db, "varaq", name="Varaq")
    resp = await client.get("/storefront/varaq")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Varaq"
    assert body["slug"] == "varaq"
    for private in ("id", "status", "plan", "trial_ends_at", "logo_key"):
        assert private not in body


async def test_storefront_slug_is_case_insensitive(client: AsyncClient, db: AsyncSession) -> None:
    await make_tenant(db, "varaq")
    assert (await client.get("/storefront/VARAQ")).status_code == 200


async def test_unknown_store_is_404(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/storefront/yoq-dokon", headers={"Accept-Language": "uz"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "store_not_found", "message": "Do\u02bbkon topilmadi."}


@pytest.mark.parametrize("hide", ["suspended", "deleted"])
async def test_hidden_store_looks_missing(client: AsyncClient, db: AsyncSession, hide: str) -> None:
    tenant = await make_tenant(db, "varaq")
    if hide == "suspended":
        tenant.status = TenantStatus.SUSPENDED
    else:
        tenant.is_active = False
    await db.commit()
    assert (await client.get("/storefront/varaq")).status_code == 404
