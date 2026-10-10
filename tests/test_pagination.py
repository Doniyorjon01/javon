from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi_pagination import add_pagination, paginate
from fastapi_pagination.utils import disable_installed_extensions_check
from httpx import ASGITransport, AsyncClient

from errors import register_exception_handlers
from utils.pagination import CustomPage


@pytest.fixture
async def paged_client() -> AsyncIterator[AsyncClient]:
    # The test paginates a plain list on purpose; real endpoints use ext.sqlalchemy.
    disable_installed_extensions_check()
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/numbers", response_model=CustomPage[int])
    async def numbers() -> object:
        return paginate(list(range(250)))

    add_pagination(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_default_page_size_is_20(paged_client: AsyncClient) -> None:
    body = (await paged_client.get("/numbers")).json()
    assert body["size"] == 20
    assert body["items"] == list(range(20))
    assert body["total"] == 250


async def test_page_size_above_100_is_rejected(paged_client: AsyncClient) -> None:
    resp = await paged_client.get("/numbers", params={"size": 101})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"
