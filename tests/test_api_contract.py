"""
The contract every endpoint inherits: error shape, language, request id.
The frontend depends on all three, so they are tested once here.
"""

from fastapi import FastAPI
from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_request_id_is_generated(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert len(resp.headers["x-request-id"]) == 32


async def test_valid_incoming_request_id_is_kept(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Request-ID": "caddy-abc-12345"})
    assert resp.headers["x-request-id"] == "caddy-abc-12345"


async def test_malformed_incoming_request_id_is_replaced(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert resp.headers["x-request-id"] != "bad id\nwith newline"
    assert len(resp.headers["x-request-id"]) == 32


async def test_unknown_route_uses_standard_error_shape(client: AsyncClient) -> None:
    resp = await client.get("/no-such-route", headers={"Accept-Language": "ru"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": {"code": "not_found", "message": "Запрошенный адрес не найден."}}


async def test_default_language_is_uzbek(client: AsyncClient) -> None:
    resp = await client.get("/no-such-route")
    assert resp.json()["detail"]["message"] == "Soʻralgan manzil topilmadi."


async def test_wrong_method(client: AsyncClient) -> None:
    resp = await client.post("/health")
    assert resp.status_code == 405
    assert resp.json()["detail"]["code"] == "method_not_allowed"


async def test_validation_error_shape(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/_test/int/{value}")
    async def _int_route(value: int) -> dict[str, int]:
        return {"value": value}

    resp = await client.get("/_test/int/abc", headers={"Accept-Language": "en"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "validation_error"
    # The first problem, as a sentence in the request's language (utils/validation.py).
    assert detail["message"] == "Enter a number."
    assert detail["errors"][0] == {"type": "int_parsing", "loc": ["path", "value"], "msg": "Enter a number."}
    # What the client sent is not echoed back.
    assert "input" not in detail["errors"][0]


async def test_unhandled_exception_becomes_standard_500(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("secret internal detail")

    resp = await client.get("/_test/boom")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "internal_error"
    assert detail["request_id"] == resp.headers["x-request-id"]
    assert "secret internal detail" not in resp.text
