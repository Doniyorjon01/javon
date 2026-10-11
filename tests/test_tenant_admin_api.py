"""The owner's side of a store: create, read, change — and who may not."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MemberRole, Membership
from tests.factories import add_member, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


async def test_create_store_makes_me_the_owner(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)

    resp = await client.post("/tenants", json={"name": "Varaq", "slug": "varaq"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "varaq"
    assert body["status"] == "trial"

    role = await db.scalar(
        select(Membership.role).where(Membership.tenant_id == body["id"], Membership.user_id == user.id)
    )
    assert role == MemberRole.OWNER
    stores = (await client.get("/auth/me")).json()["stores"]
    assert [s["slug"] for s in stores] == ["varaq"]


async def test_create_store_needs_sign_in(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post("/tenants", json={"name": "Varaq", "slug": "varaq"})
    assert resp.status_code == 401


async def test_create_store_with_taken_slug(client: AsyncClient, db: AsyncSession) -> None:
    await make_tenant(db, "varaq")
    await sign_in(client, await make_user(db))
    resp = await client.post("/tenants", json={"name": "Varaq 2", "slug": "varaq"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "slug_taken"


async def test_client_cannot_choose_status_or_plan(client: AsyncClient, db: AsyncSession) -> None:
    await sign_in(client, await make_user(db))
    resp = await client.post("/tenants", json={"name": "Varaq", "slug": "varaq", "status": "active"})
    assert resp.status_code == 422


async def test_owner_reads_and_updates_store(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)

    assert (await client.get(f"/tenants/{tenant.id}")).json()["slug"] == "varaq"

    resp = await client.patch(
        f"/tenants/{tenant.id}", json={"accent_color": "#1F4D3F", "phone": "+998 90 123 45 67"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accent_color"] == "#1F4D3F"
    assert resp.json()["phone"] == "+998901234567"


async def test_staff_can_read_but_not_change_settings(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    staff = await make_user(db, "Staff")
    await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)

    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 200
    resp = await client.patch(f"/tenants/{tenant.id}", json={"accent_color": "#000000"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "forbidden"


async def test_someone_elses_store_looks_missing(client: AsyncClient, db: AsyncSession) -> None:
    """IDOR guard: guessing another store's id must reveal nothing, not even that it exists."""
    others = await make_tenant(db, "boshqa")
    await sign_in(client, await make_user(db))

    for method in ("get", "patch"):
        kwargs = {"json": {"accent_color": "#000000"}} if method == "patch" else {}
        resp = await getattr(client, method)(f"/tenants/{others.id}", **kwargs)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "store_not_found"
    assert (await client.get("/tenants/999999")).status_code == 404


async def test_removed_member_loses_access(client: AsyncClient, db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    staff = await make_user(db)
    membership = await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    membership.is_active = False
    await db.commit()
    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 404


async def test_write_from_foreign_origin_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """CSRF guard: a page on another site cannot use the owner's cookie to change the store."""
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)

    client.headers["Origin"] = "https://evil.example"
    resp = await client.patch(f"/tenants/{tenant.id}", json={"accent_color": "#000000"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "origin_not_allowed"
    # Reads are not state-changing and stay allowed.
    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 200
