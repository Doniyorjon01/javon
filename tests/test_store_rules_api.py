"""
Store rules through the HTTP API: how many stores an account may open, the
launch step, what a suspended store may still do, and request limits.
"""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import MemberRole, Membership, Tenant, TenantStatus
from tests.factories import add_member, make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


# --------------------------------------------------------------------------- #
# Store limit per account
# --------------------------------------------------------------------------- #
async def test_second_store_is_refused_until_admin_raises_the_limit(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db)
    admin = await make_user(db, "Admin", is_platform_admin=True)
    await sign_in(client, user)
    assert (await client.post("/tenants", json={"name": "Varaq", "slug": "varaq"})).status_code == 201

    second = await client.post("/tenants", json={"name": "Varaq 2", "slug": "varaq-2"})
    assert second.status_code == 403
    assert second.json()["detail"]["code"] == "store_limit_reached"
    assert "(1)" in second.json()["detail"]["message"]

    await sign_in(client, admin)
    raised = await client.patch(f"/system/users/{user.id}", json={"max_stores": 2})
    assert raised.status_code == 200, raised.text
    assert raised.json()["max_stores"] == 2

    await sign_in(client, user)
    assert (await client.post("/tenants", json={"name": "Varaq 2", "slug": "varaq-2"})).status_code == 201


async def test_parallel_store_creation_cannot_beat_the_limit(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)

    responses = await asyncio.gather(
        *(client.post("/tenants", json={"name": f"Store {i}", "slug": f"store-{i}"}) for i in range(8))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 1, codes
    assert set(codes) == {201, 403}
    owned = await db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user.id))
    assert owned == 1


async def test_staff_membership_does_not_count_toward_the_limit(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db)
    await add_member(db, await make_tenant(db, "boshqa"), user, MemberRole.STAFF)
    await sign_in(client, user)
    assert (await client.post("/tenants", json={"name": "Varaq", "slug": "varaq"})).status_code == 201


async def test_user_admin_routes_are_for_platform_admins_only(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)
    assert (await client.get("/system/users")).status_code == 403
    assert (await client.patch(f"/system/users/{user.id}", json={"max_stores": 50})).status_code == 403


async def test_admin_finds_user_by_telegram_id_and_limits_are_validated(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, "Kitobchi")
    await make_user(db, "Boshqa")
    await sign_in(client, await make_user(db, "Admin", is_platform_admin=True))

    found = (await client.get("/system/users", params={"telegram_id": user.telegram_id})).json()
    assert [u["id"] for u in found["items"]] == [user.id]
    assert found["items"][0]["max_stores"] == 1

    assert (await client.patch(f"/system/users/{user.id}", json={"max_stores": 101})).status_code == 422
    assert (
        await client.patch(f"/system/users/{user.id}", json={"is_platform_admin": True})
    ).status_code == 422
    missing = await client.patch("/system/users/999999", json={"max_stores": 2})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "user_not_found"


# --------------------------------------------------------------------------- #
# Launch
# --------------------------------------------------------------------------- #
async def test_storefront_is_hidden_until_the_owner_launches(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    staff = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner, launched=False)
    await add_member(db, tenant, staff, MemberRole.STAFF)

    assert (await client.get("/storefront/varaq")).status_code == 404
    await sign_in(client, owner)
    me = (await client.get("/auth/me")).json()
    assert me["stores"][0]["launched_at"] is None

    await sign_in(client, staff)
    assert (await client.post(f"/tenants/{tenant.id}/launch")).status_code == 403

    await sign_in(client, owner)
    launched = await client.post(f"/tenants/{tenant.id}/launch")
    assert launched.status_code == 200, launched.text
    first_launch = launched.json()["launched_at"]
    assert first_launch is not None
    assert (await client.get("/storefront/varaq")).status_code == 200

    # Pressing it again changes nothing.
    again = await client.post(f"/tenants/{tenant.id}/launch")
    assert again.json()["launched_at"] == first_launch


# --------------------------------------------------------------------------- #
# Suspended store: read-only
# --------------------------------------------------------------------------- #
async def test_suspended_store_can_be_read_but_not_changed(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(status=TenantStatus.SUSPENDED))
    await db.commit()
    await sign_in(client, owner)

    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 200
    for method, path, body in (
        ("PATCH", f"/tenants/{tenant.id}", {"accent_color": "#000000"}),
        ("POST", f"/tenants/{tenant.id}/catalog/books", {"title": "Kitob", "authors": ["Muallif Bir"]}),
        ("POST", f"/tenants/{tenant.id}/launch", None),
    ):
        resp = await client.request(method, path, json=body)
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["detail"]["code"] == "store_suspended"
    assert (await client.get("/storefront/varaq")).status_code == 404


# --------------------------------------------------------------------------- #
# Request limits
# --------------------------------------------------------------------------- #
async def test_out_of_range_ids_are_422_not_500(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db, is_platform_admin=True)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    huge = "99999999999999999999"
    for path in (
        f"/tenants/{huge}",
        f"/tenants/{tenant.id}/catalog/books/{huge}",
        f"/system/users?telegram_id={huge}",
    ):
        assert (await client.get(path)).status_code == 422, path
    assert (await client.patch(f"/system/users/{huge}", json={"max_stores": 1})).status_code == 422
