import time

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.db_user import hash_token
from models import User, UserSession
from tests.conftest import TEST_BOT_TOKEN
from tests.factories import make_tenant, make_user, sign_in
from utils.telegram_auth import sign_login_widget

pytestmark = pytest.mark.db


def widget_payload(telegram_id: int = 777, **overrides: object) -> dict:
    payload: dict = {
        "id": telegram_id,
        "first_name": "Doniyor",
        "username": "doniyor",
        "auth_date": int(time.time()),
        **overrides,
    }
    payload["hash"] = sign_login_widget(payload, TEST_BOT_TOKEN)
    return payload


def session_cookie(client: AsyncClient) -> str | None:
    return client.cookies.get(settings.SESSION_COOKIE_NAME)


async def test_telegram_login_creates_user_and_session(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post("/auth/telegram", json=widget_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["first_name"] == "Doniyor"
    assert body["stores"] == []

    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    token = session_cookie(client)
    stored = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    assert stored is not None
    assert stored.token_hash != token  # only the hash is stored


async def test_second_login_updates_name_not_duplicates(client: AsyncClient, db: AsyncSession) -> None:
    await client.post("/auth/telegram", json=widget_payload(first_name="Old"))
    await client.post("/auth/telegram", json=widget_payload(first_name="New"))
    users = list(await db.scalars(select(User).where(User.telegram_id == 777)))
    assert [u.first_name for u in users] == ["New"]


async def test_relogin_revokes_previous_session(client: AsyncClient, db: AsyncSession) -> None:
    await client.post("/auth/telegram", json=widget_payload())
    first = session_cookie(client)
    await client.post("/auth/telegram", json=widget_payload())
    assert session_cookie(client) != first
    old = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(first)))
    assert old.is_active is False


async def test_extra_widget_fields_are_part_of_the_signature(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post("/auth/telegram", json=widget_payload(future_field="x"))
    assert resp.status_code == 200, resp.text


async def test_forged_payload_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    payload = widget_payload()
    payload["id"] = 1
    resp = await client.post("/auth/telegram", json=payload)
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "telegram_auth_invalid"
    assert session_cookie(client) is None


async def test_stale_payload_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    payload = widget_payload(auth_date=int(time.time()) - settings.TELEGRAM_AUTH_MAX_AGE_S - 10)
    resp = await client.post("/auth/telegram", json=payload)
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "telegram_auth_expired"


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
async def test_login_from_foreign_origin_is_refused(
    client: AsyncClient, db: AsyncSession, origin: str | None
) -> None:
    if origin is None:
        del client.headers["Origin"]
    else:
        client.headers["Origin"] = origin
    resp = await client.post("/auth/telegram", json=widget_payload())
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "origin_not_allowed"


async def test_disabled_user_cannot_sign_in(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    user.is_active = False
    await db.commit()
    resp = await client.post(
        "/auth/dev-login", json={"telegram_id": user.telegram_id, "first_name": user.first_name}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "account_disabled"


async def test_me_requires_a_session(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
    client.cookies.set(settings.SESSION_COOKIE_NAME, "made-up-token")
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_lists_my_stores(client: AsyncClient, db: AsyncSession) -> None:
    owner = await make_user(db, "Owner")
    await make_tenant(db, "varaq", owner, name="Varaq")
    await make_tenant(db, "boshqa")  # someone else's store
    await sign_in(client, owner)

    body = (await client.get("/auth/me")).json()
    assert body["user"]["first_name"] == "Owner"
    assert [(s["slug"], s["role"], s["status"]) for s in body["stores"]] == [("varaq", "owner", "trial")]


async def test_logout_revokes_the_session(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)
    token = session_cookie(client)

    resp = await client.post("/auth/logout")
    assert resp.status_code == 204
    # Even if the browser kept the cookie, the server no longer accepts it.
    client.cookies.set(settings.SESSION_COOKIE_NAME, token)
    assert (await client.get("/auth/me")).status_code == 401
    # Logging out twice is fine.
    assert (await client.post("/auth/logout")).status_code == 204


async def test_expired_session_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)
    await db.execute(update(UserSession).values(expires_at=UserSession.created_at))
    await db.commit()
    assert (await client.get("/auth/me")).status_code == 401


async def test_disabling_a_user_ends_their_sessions(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await sign_in(client, user)
    user.is_active = False
    await db.commit()
    assert (await client.get("/auth/me")).status_code == 401
