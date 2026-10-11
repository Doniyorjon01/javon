"""
Database engine and session
===========================
`db: AsyncSession = Depends(get_pg_db)` in every route, same as hik-backend.

The engine is created once per process. Background work (arq jobs, outbox) must
open its own short session with `SessionLocal()`: the request's session is
already closed by the time that work runs.

Tenant scoping (Row Level Security)
-----------------------------------
`await bind_tenant(db, tenant_id)` marks a session as working for one store.
From then on, EVERY transaction the session begins first runs

    SELECT set_config('app.tenant_id', '<id>', true)   -- true = this transaction only

so the RLS policies (database/rls.py) see only that store's rows. Because the
setting is transaction-local, it disappears at COMMIT/ROLLBACK and can never
leak to the next request that gets the same pooled connection.

Route code does not call bind_tenant itself: tenant dependencies do
(auth/tenant.py for the storefront; the member dependency in step 3).
"""

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction

from config import settings
from database.rls import TENANT_SETTING

TENANT_KEY = "tenant_id"

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


class TenantAwareSession(Session):
    """The sync session behind every AsyncSession; carries the after_begin hook below."""


@event.listens_for(TenantAwareSession, "after_begin")
def _apply_tenant(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is not None:
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )


SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
    sync_session_class=TenantAwareSession,
)


async def get_pg_db() -> AsyncIterator[AsyncSession]:
    # Closing the session rolls back anything not committed by the db layer.
    async with SessionLocal() as session:
        yield session


async def bind_tenant(db: AsyncSession, tenant_id: int) -> None:
    current = db.info.get(TENANT_KEY)
    if current is not None and current != tenant_id:
        raise RuntimeError(f"session is already bound to tenant {current}, refusing {tenant_id}")
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("bind_tenant() called with unflushed changes in the session")
    if db.in_transaction():
        # The lookup that found the tenant ran in a transaction WITHOUT the tenant
        # setting. End it (read-only, nothing to lose) so the next one gets the hook.
        await db.commit()
    db.info[TENANT_KEY] = tenant_id
