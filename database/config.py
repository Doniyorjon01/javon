"""
Database engine and session
===========================
`db: AsyncSession = Depends(get_pg_db)` in every route, same as hik-backend.

The engine is created once per process. Background work (arq jobs, outbox) must
open its own short session with `SessionLocal()`: the request's session is
already closed by the time that work runs.

Coming in step 2: a tenant-scoped session that runs
`SET LOCAL app.tenant_id = ...` at the start of every transaction, so the
Row Level Security policies see which store the request belongs to.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "application_name": "javon-backend",
            "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
            # A transaction left open by a bug must not hold row locks forever.
            "idle_in_transaction_session_timeout": "60000",
        }
    },
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_pg_db() -> AsyncIterator[AsyncSession]:
    # Closing the session rolls back anything not committed by the db layer.
    async with SessionLocal() as session:
        yield session
