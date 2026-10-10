"""
javon.uz API
============
`main:app` is what uvicorn runs. `create_app()` exists so tests can build a
fresh instance.

Long-lived clients (Redis now; S3 storage and the Telegram bot manager later)
are created once in `lifespan` and kept on `app.state`, as in hik-backend's
detector_control client.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from config import VERSION, settings
from database.config import engine
from errors import register_exception_handlers
from middleware import RequestContextMiddleware
from routers import health, storefront, tenants
from utils.log import configure_logging
from utils.redis_cache import create_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = create_redis(str(settings.REDIS_URL))
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="javon.uz API",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    register_exception_handlers(app)

    # Order matters: the middleware added last runs first. CORS wraps the request
    # context, so even our 500 responses carry CORS headers.
    app.add_middleware(RequestContextMiddleware)
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    app.include_router(health.router)
    app.include_router(health.router)
    app.include_router(tenants.router)
    app.include_router(storefront.router)

    add_pagination(app)
    return app


app = create_app()
