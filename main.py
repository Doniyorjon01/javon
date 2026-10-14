"""
javon.uz API
============
`main:app` is what uvicorn runs. `create_app()` exists so tests can build a
fresh instance.

Long-lived clients (Redis, S3 storage; the Telegram bot manager later) are
created once in `lifespan` and kept on `app.state`, as in hik-backend's
detector_control client.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from auth import authentication
from config import VERSION, settings
from database.config import engine
from errors import register_exception_handlers
from middleware import BodySizeLimitMiddleware, RequestContextMiddleware, StorefrontCORSMiddleware
from routers import catalog, health, inventory, orders, storefront, system, telegram, tenants
from services.storage import create_storage
from services.telegram import TelegramClient
from utils.log import configure_logging
from utils.redis_cache import create_redis

# Routes that accept a file: they get MAX_UPLOAD_BYTES instead of the 1 MB JSON limit.
UPLOAD_PATHS = re.compile(
    r"^/(tenants/\d+/(logo|catalog/books/\d+/cover|inventory/imports)"
    r"|system/catalog/books/\d+/cover"
    r"|storefront/[a-z0-9-]+/orders/\d+/payment-proof)$"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = create_redis(str(settings.REDIS_URL))
    # None when STORAGE_* is not configured: upload routes then answer 503.
    if not hasattr(app.state, "storage"):  # tests may install fakes first
        app.state.storage = create_storage()
        app.state.private_storage = create_storage(settings.STORAGE_PRIVATE_BUCKET)
    if not hasattr(app.state, "telegram"):
        app.state.telegram = TelegramClient()
    try:
        yield
    finally:
        await app.state.telegram.aclose()
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

    # Order matters: the middleware added last runs first, so a request passes
    # storefront CORS -> CORS -> request context (id, access log, 500s) -> body size
    # limit -> routes. CORS wraps everything, so even our 413 and 500 responses
    # carry CORS headers.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.MAX_REQUEST_BODY_BYTES,
        upload_max_bytes=settings.MAX_UPLOAD_BYTES,
        upload_paths=UPLOAD_PATHS,
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.CORS_ORIGINS:
        # Our own frontend: exact origins, cookies allowed.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    if settings.CORS_ORIGIN_REGEX:
        # Store subdomains: the public storefront API only, never with cookies.
        app.add_middleware(
            StorefrontCORSMiddleware,
            origin_regex=settings.CORS_ORIGIN_REGEX,
            trusted_origins=settings.CORS_ORIGINS,
        )

    app.include_router(health.router)
    app.include_router(authentication.router)
    if settings.dev_login_enabled:
        app.include_router(authentication.dev_router)
    app.include_router(tenants.router)
    app.include_router(storefront.router)
    app.include_router(catalog.router)
    app.include_router(inventory.router)
    app.include_router(orders.router)
    app.include_router(orders.public_router)
    app.include_router(telegram.router)
    app.include_router(telegram.webhook_router)
    app.include_router(telegram.mini_app_router)
    app.include_router(system.router)

    add_pagination(app)
    return app


app = create_app()
