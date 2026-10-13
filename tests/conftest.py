"""
Test setup
==========
Two kinds of tests:

  * unit tests — no database, always run;
  * database tests — marked `pytestmark = pytest.mark.db`, run against a real
    PostgreSQL test database. They are SKIPPED unless TEST_DATABASE_URL and
    TEST_MIGRATION_DATABASE_URL are set (in the environment or in .env).

Database tests wipe every table between tests, so the test database name must
end with "_test" — a guard against pointing them at real data by mistake.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
_dotenv = dotenv_values(ROOT / ".env")


def _from_env(key: str) -> str | None:
    return os.environ.get(key) or _dotenv.get(key) or None


TEST_DATABASE_URL = _from_env("TEST_DATABASE_URL")
TEST_MIGRATION_DATABASE_URL = _from_env("TEST_MIGRATION_DATABASE_URL")
DB_AVAILABLE = bool(TEST_DATABASE_URL and TEST_MIGRATION_DATABASE_URL)

# Settings are read at import time, so the environment is fixed before the app loads.
# Forced, not setdefault: tests must never pick up the development database from .env.
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+asyncpg://javon_app:x@localhost:5432/javon_test"
os.environ["MIGRATION_DATABASE_URL"] = (
    TEST_MIGRATION_DATABASE_URL or "postgresql+asyncpg://javon_owner:x@localhost:5432/javon_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
# Sign-in: a fake platform bot token, the frontend origin tests send, plain-http cookies.
TEST_BOT_TOKEN = "123456:TEST-login-bot-token"
TRUSTED_ORIGIN = "http://frontend.test"
os.environ["TELEGRAM_LOGIN_BOT_TOKEN"] = TEST_BOT_TOKEN
os.environ["CORS_ORIGINS"] = f'["{TRUSTED_ORIGIN}"]'
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ.pop("SESSION_COOKIE_DOMAIN", None)
# Files: tests use MemoryStorage (fixture below), never a real bucket from .env.
os.environ["STORAGE_ACCESS_KEY"] = ""
os.environ["STORAGE_SECRET_KEY"] = ""
os.environ["STORAGE_PUBLIC_URL"] = "http://media.test/javon-media"
os.environ["CORS_ORIGIN_REGEX"] = ""

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database.config import SessionLocal, engine
from main import create_app
from models import Base
from services.storage import MemoryStorage


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DB_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="set TEST_DATABASE_URL and TEST_MIGRATION_DATABASE_URL to run")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
@pytest.fixture
def storage() -> MemoryStorage:
    """Files the app stored during the test (no MinIO needed)."""
    return MemoryStorage()


@pytest.fixture
def app(storage: MemoryStorage) -> FastAPI:
    app = create_app()
    app.state.storage = storage
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        LifespanManager(app),
        # Like our frontend: every request carries the trusted Origin (CSRF check).
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": TRUSTED_ORIGIN}
        ) as http,
    ):
        yield http


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def migrated_db() -> None:
    """downgrade base + upgrade head once per run: proves the migrations work both ways."""
    for url in (TEST_DATABASE_URL, TEST_MIGRATION_DATABASE_URL):
        name = make_url(url).database or ""
        if not name.endswith("_test"):
            pytest.exit(f"refusing to run database tests against '{name}': name must end with _test")

    env = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "MIGRATION_DATABASE_URL": TEST_MIGRATION_DATABASE_URL,
    }
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        result = subprocess.run(  # noqa: S603 — fixed arguments, no user input
            [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True
        )
        if result.returncode != 0:
            pytest.exit(f"alembic {' '.join(args)} failed:\n{result.stderr}")


@pytest.fixture
async def owner_engine(migrated_db: None) -> AsyncIterator[AsyncEngine]:
    """Schema-owner connection: wipes tables and sets up what the API role may not."""
    owner = create_async_engine(TEST_MIGRATION_DATABASE_URL, poolclass=NullPool)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with owner.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield owner
    await owner.dispose()
    # The app engine's pooled connections belong to this test's event loop.
    await engine.dispose()


@pytest.fixture
async def db(owner_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session exactly like a request's: API role, RLS applies."""
    async with SessionLocal() as session:
        yield session
