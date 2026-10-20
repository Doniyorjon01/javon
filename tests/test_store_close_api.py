"""The owner pauses, resumes and deletes their store."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MemberRole, Tenant
from tests.factories import add_member, make_book, make_item, make_tenant, make_user, sign_in
from tests.fake_telegram import TOKEN, FakeTelegram

pytestmark = pytest.mark.db


async def order(client: AsyncClient, book_id: int) -> int:
    resp = await client.post(
        "/storefront/varaq/orders",
        json={
            "idempotency_key": str(uuid.uuid4()),
            "customer_name": "Aziz",
            "phone": "93 111 22 33",
            "delivery_type": "pickup",
            "items": [{"book_id": book_id, "quantity": 1}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_pause_hides_the_storefront_only(client: AsyncClient, db: AsyncSession) -> None:
    owner, staff = await make_user(db), await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await add_member(db, tenant, staff, MemberRole.STAFF)
    await sign_in(client, staff)
    assert (await client.post(f"/tenants/{tenant.id}/pause")).status_code == 403

    await sign_in(client, owner)
    paused = await client.post(f"/tenants/{tenant.id}/pause")
    assert paused.status_code == 200 and paused.json()["paused_at"] is not None
    assert (await client.get("/storefront/varaq")).status_code == 404
    # The panel keeps working while paused.
    assert (await client.patch(f"/tenants/{tenant.id}", json={"name": "Varaq 2"})).status_code == 200
    assert (await client.get("/auth/me")).json()["stores"][0]["paused_at"] is not None

    resumed = await client.post(f"/tenants/{tenant.id}/resume")
    assert resumed.json()["paused_at"] is None
    assert (await client.get("/storefront/varaq")).status_code == 200


async def test_delete_needs_the_slug_and_no_unfinished_orders(
    client: AsyncClient, db: AsyncSession, telegram: FakeTelegram
) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    item = await make_item(tenant, await make_book(db))
    order_id = await order(client, item.book_id)
    await sign_in(client, owner)
    assert (await client.put(f"/tenants/{tenant.id}/telegram", json={"token": TOKEN})).status_code == 200

    wrong = await client.request("DELETE", f"/tenants/{tenant.id}", json={"confirm_slug": "boshqa"})
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "store_delete_confirm"
    busy = await client.request("DELETE", f"/tenants/{tenant.id}", json={"confirm_slug": "varaq"})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "store_has_open_orders"

    await client.post(f"/tenants/{tenant.id}/orders/{order_id}/status", json={"status": "cancelled"})
    gone = await client.request("DELETE", f"/tenants/{tenant.id}", json={"confirm_slug": " VARAQ "})
    assert gone.status_code == 204
    assert "deleteWebhook" in telegram.methods()  # the bot stops answering buyers

    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 404
    assert (await client.get("/storefront/varaq")).status_code == 404
    assert (await client.get("/auth/me")).json()["stores"] == []
    assert await db.scalar(select(Tenant.is_active).where(Tenant.id == tenant.id)) is False
    # A new store may be opened in its place (the old slug stays taken).
    again = await client.post("/tenants", json={"name": "Varaq", "slug": "varaq"})
    assert again.status_code == 409
    new = await client.post("/tenants", json={"name": "Varaq", "slug": "varaq-yangi"})
    assert new.status_code == 201
