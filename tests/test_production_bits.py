"""Pieces for running on a server: the TLS ask route, Sentry scrubbing, sign-in limits."""

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from tests.factories import make_tenant
from utils import sentry

TOKEN = "777000111:AAH-fake_token_for_tests_only_abcdefghij"


@pytest.fixture
async def clean_redis() -> AsyncIterator[None]:
    redis = Redis.from_url(str(settings.REDIS_URL))
    await redis.flushdb()
    yield
    await redis.aclose()


@pytest.mark.db
async def test_tls_ask_only_for_existing_stores(client: AsyncClient, db: AsyncSession) -> None:
    await make_tenant(db, "varaq", launched=False)
    for domain, expected in [
        ("varaq.javon.uz", 200),
        ("VARAQ.javon.uz.", 200),
        ("nope.javon.uz", 404),
        ("a.varaq.javon.uz", 404),
        ("varaq.example.com", 404),
        ("javon.uz", 404),
    ]:
        resp = await client.get("/internal/tls-ask", params={"domain": domain})
        assert resp.status_code == expected, domain
    assert "/internal/tls-ask" not in (await client.get("/openapi.json")).text


@pytest.mark.db
async def test_sign_in_is_rate_limited(
    client: AsyncClient, db: AsyncSession, clean_redis: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)
    codes = [
        (await client.post("/auth/dev-login", json={"telegram_id": 5, "first_name": "A"})).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    resp = await client.post("/auth/telegram", json={})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == str(settings.AUTH_RATE_WINDOW_S)


def test_sentry_events_carry_no_personal_data() -> None:
    event = {
        "request": {
            "method": "GET",
            "url": "https://api.javon.uz/storefront/varaq/orders/5",
            "query_string": "token=secret-tracking-token",
            "headers": {"Cookie": "javon_session=abc", "X-Telegram-Init-Data": "user=..."},
            "data": {"phone": "+998901234567", "address": "Chilonzor"},
            "cookies": {"javon_session": "abc"},
        },
        "user": {"ip_address": "1.2.3.4"},
        "server_name": "javon-prod-1",
        "exception": {"values": [{"value": f"call https://api.telegram.org/bot{TOKEN}/sendMessage failed"}]},
        "breadcrumbs": {
            "values": [
                {"category": "httplib", "data": {"url": f"https://api.telegram.org/bot{TOKEN}/getMe"}},
                {"category": "javon.request", "message": "POST /orders -> 201"},
            ]
        },
    }
    clean = sentry.scrub_event(event)
    assert clean["request"] == {"method": "GET", "url": "https://api.javon.uz/storefront/varaq/orders/5"}
    assert "user" not in clean and "server_name" not in clean
    text = str(clean)
    assert TOKEN not in text and "+998" not in text and "secret-tracking-token" not in text
    assert [crumb["category"] for crumb in clean["breadcrumbs"]["values"]] == ["javon.request"]
    assert sentry.scrub_breadcrumb({"category": "http", "data": {}}) is None
    assert sentry.scrub_breadcrumb({"category": "log", "message": TOKEN, "data": {"x": 1}}) == {
        "category": "log",
        "message": "<bot-token>",
    }


def test_sentry_is_off_without_a_dsn() -> None:
    assert settings.SENTRY_DSN is None
    assert sentry.init_sentry("test") is False
