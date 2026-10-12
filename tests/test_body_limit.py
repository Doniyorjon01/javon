"""Oversized request bodies are refused with 413 before the app reads them."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from main import create_app
from tests.conftest import TRUSTED_ORIGIN

LIMIT = 1024


@pytest.fixture
async def http(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", LIMIT)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Origin": TRUSTED_ORIGIN}
    ) as c:
        yield c


async def test_declared_length_over_the_limit(http: AsyncClient) -> None:
    resp = await http.post(
        "/auth/dev-login",
        content=b"x" * (LIMIT + 1),
        headers={"Content-Type": "application/json", "Accept-Language": "en"},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == {
        "code": "payload_too_large",
        "message": "The request is too large (at most 1 KB).",
    }


async def test_chunked_body_over_the_limit(http: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * 512

    resp = await http.post("/auth/dev-login", content=chunks(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "payload_too_large"


async def test_body_within_the_limit_reaches_the_route(http: AsyncClient) -> None:
    resp = await http.post("/auth/dev-login", json={})
    assert resp.status_code == 422  # the route ran and validated the body
