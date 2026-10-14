"""Staff invites, members, the plan's staff limit and store isolation."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import StaffInvite, Tenant, User
from tests.conftest import TRUSTED_ORIGIN
from tests.factories import make_tenant, make_user, sign_in

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
async def clean_rate_limits() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


def token_of(url: str) -> str:
    assert url.startswith("https://javon.uz/taklif/")
    return url.rsplit("/", 1)[1]


async def invite(client: AsyncClient, tenant: Tenant) -> str:
    resp = await client.post(f"/tenants/{tenant.id}/staff/invites")
    assert resp.status_code == 201, resp.text
    return token_of(resp.json()["url"])


async def accept_as(client: AsyncClient, user: User, token: str) -> int:
    await sign_in(client, user)
    return (await client.post(f"/invites/{token}/accept")).status_code


async def test_invite_accept_work_and_removal(client: AsyncClient, db: AsyncSession) -> None:
    owner, colleague = await make_user(db, "Owner"), await make_user(db, "Kamola")
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    token = await invite(client, tenant)
    assert len((await client.get(f"/tenants/{tenant.id}/staff/invites")).json()) == 1

    # The invited person sees the store's name before signing in.
    client.cookies.clear()
    preview = await client.get(f"/invites/{token}")
    assert preview.status_code == 200
    assert preview.json()["store_name"] == "Test store"
    assert (await client.post(f"/invites/{token}/accept")).status_code == 401

    await sign_in(client, colleague)
    joined = await client.post(f"/invites/{token}/accept")
    assert joined.status_code == 200
    assert joined.json() == {"tenant_id": tenant.id, "slug": "varaq", "name": "Test store", "role": "staff"}
    # Staff work with orders but do not manage people or see the subscription.
    assert (await client.get(f"/tenants/{tenant.id}/orders")).status_code == 200
    assert (await client.post(f"/tenants/{tenant.id}/staff/invites")).status_code == 403
    assert (await client.get(f"/tenants/{tenant.id}/staff")).status_code == 403

    # The link worked once.
    assert (await client.get(f"/invites/{token}")).status_code == 404

    await sign_in(client, owner)
    members = (await client.get(f"/tenants/{tenant.id}/staff")).json()
    assert [(m["first_name"], m["role"]) for m in members] == [("Owner", "owner"), ("Kamola", "staff")]
    assert (await client.get(f"/tenants/{tenant.id}/staff/invites")).json() == []
    resp = await client.delete(f"/tenants/{tenant.id}/staff/{owner.id}")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "owner_cannot_leave"
    assert (await client.delete(f"/tenants/{tenant.id}/staff/{colleague.id}")).status_code == 204
    assert (await client.delete(f"/tenants/{tenant.id}/staff/{colleague.id}")).status_code == 404

    # Removed: the store is gone for them from the next request.
    await sign_in(client, colleague)
    assert (await client.get(f"/tenants/{tenant.id}/orders")).status_code == 404


async def test_revoked_expired_and_wrong_links(client: AsyncClient, db: AsyncSession) -> None:
    owner, other = await make_user(db), await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    other_store = await make_tenant(db, "kitobxon", other)
    await sign_in(client, owner)
    revoked, expired = await invite(client, tenant), await invite(client, tenant)
    invite_id = (await client.get(f"/tenants/{tenant.id}/staff/invites")).json()[-1]["id"]

    # Another store's owner cannot touch it.
    await sign_in(client, other)
    assert (await client.delete(f"/tenants/{other_store.id}/staff/invites/{invite_id}")).status_code == 404

    await sign_in(client, owner)
    assert (await client.delete(f"/tenants/{tenant.id}/staff/invites/{invite_id}")).status_code == 204
    await db.execute(
        update(StaffInvite)
        .where(StaffInvite.tenant_id == tenant.id, StaffInvite.is_active.is_(True))
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    for token in (revoked, expired, "x" * 32, "short"):
        resp = await client.get(f"/invites/{token}")
        assert resp.status_code in (404, 422)
    resp = await client.post(f"/invites/{revoked}/accept")
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "invite_invalid"


async def test_staff_limit_and_already_member(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(plan="start"))  # 1 staff
    await db.commit()
    await sign_in(client, owner)
    first, second = await invite(client, tenant), await invite(client, tenant)

    resp = await client.post(f"/invites/{first}/accept")  # the owner's own link
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "already_member"

    assert await accept_as(client, await make_user(db), first) == 200
    resp_code = await accept_as(client, await make_user(db), second)
    assert resp_code == 409
    await sign_in(client, owner)
    resp = await client.post(f"/tenants/{tenant.id}/staff/invites")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "staff_limit_reached"


async def test_parallel_accepts_respect_the_limit(app: FastAPI, db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(plan="start"))
    await db.commit()

    async def new_client() -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": TRUSTED_ORIGIN}
        )

    async with LifespanManager(app):
        clients = [await new_client() for _ in range(4)]
        await sign_in(clients[0], owner)
        tokens = [token_of((await clients[0].post(f"/tenants/{tenant.id}/staff/invites")).json()["url"])]
        tokens.append(token_of((await clients[0].post(f"/tenants/{tenant.id}/staff/invites")).json()["url"]))
        tokens.append(token_of((await clients[0].post(f"/tenants/{tenant.id}/staff/invites")).json()["url"]))
        users = [await make_user(db) for _ in range(3)]
        for http, user in zip(clients[1:], users, strict=True):
            await sign_in(http, user)
        codes = await asyncio.gather(
            *(http.post(f"/invites/{token}/accept") for http, token in zip(clients[1:], tokens, strict=True))
        )
        for http in clients:
            await http.aclose()
    assert sorted(resp.status_code for resp in codes) == [200, 409, 409]


async def test_staff_can_leave_and_a_closed_store_takes_nobody(client: AsyncClient, db: AsyncSession) -> None:
    owner, colleague = await make_user(db), await make_user(db)
    tenant = await make_tenant(db, "varaq", owner)
    await sign_in(client, owner)
    token, later = await invite(client, tenant), await invite(client, tenant)
    assert (await client.post(f"/tenants/{tenant.id}/staff/leave")).status_code == 409
    assert await accept_as(client, colleague, token) == 200
    assert (await client.post(f"/tenants/{tenant.id}/staff/leave")).status_code == 204
    assert (await client.get(f"/tenants/{tenant.id}")).status_code == 404

    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant.id)
        .values(trial_ends_at=datetime.now(UTC) - timedelta(days=10))
    )
    await db.commit()
    resp_code = await accept_as(client, await make_user(db), later)
    assert resp_code == 403


async def test_invite_links_are_rate_limited(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 3)
    codes = [(await client.get(f"/invites/{'a' * 32}")).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]
