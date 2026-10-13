"""Store subdomains may call the public storefront API, never with cookies."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from main import create_app
from tests.conftest import TRUSTED_ORIGIN

STORE = "https://varaq.javon.uz"


@pytest.fixture
async def http(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "CORS_ORIGIN_REGEX", r"https://[a-z0-9-]+\.javon\.uz")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


async def test_preflight_from_a_store_subdomain(http: AsyncClient) -> None:
    resp = await http.options(
        "/storefront/varaq/orders",
        headers={"Origin": STORE, "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == STORE
    assert "access-control-allow-credentials" not in resp.headers


async def test_storefront_responses_carry_cors_without_credentials(http: AsyncClient) -> None:
    resp = await http.get("/storefront/varaq/no-such-page", headers={"Origin": STORE})
    assert resp.status_code == 404
    assert resp.headers["access-control-allow-origin"] == STORE
    assert "access-control-allow-credentials" not in resp.headers


@pytest.mark.parametrize("path", ["/tenants/1", "/auth/me", "/system/users"])
async def test_admin_api_is_closed_to_store_subdomains(http: AsyncClient, path: str) -> None:
    resp = await http.get(path, headers={"Origin": STORE})
    assert "access-control-allow-origin" not in resp.headers


async def test_other_sites_get_nothing(http: AsyncClient) -> None:
    for origin in ("https://evil.com", "https://varaq.javon.uz.evil.com", "http://varaq.javon.uz"):
        resp = await http.get("/storefront/varaq/no-such-page", headers={"Origin": origin})
        assert "access-control-allow-origin" not in resp.headers, origin


async def test_our_frontend_keeps_credentials(http: AsyncClient) -> None:
    resp = await http.options(
        "/storefront/varaq/orders",
        headers={"Origin": TRUSTED_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert resp.headers["access-control-allow-origin"] == TRUSTED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"
