"""
Row Level Security — the tenant isolation every store-owned table will rely on.

No store-owned table exists yet, so each test creates a probe table exactly the
way a migration would (database.rls.enable_tenant_rls) and checks it through the
API role's session (database.config).
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from database.config import SessionLocal, bind_tenant
from database.rls import disable_tenant_rls, enable_tenant_rls

pytestmark = pytest.mark.db


@pytest.fixture
async def probe(owner_engine: AsyncEngine) -> AsyncIterator[None]:
    async with owner_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE rls_probe (tenant_id bigint NOT NULL, note text NOT NULL)"))
        for stmt in enable_tenant_rls("rls_probe"):
            await conn.execute(text(stmt))
        await conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON rls_probe TO javon_app"))
        # The owner is not subject to RLS (no FORCE), so it can seed both stores.
        await conn.execute(text("INSERT INTO rls_probe VALUES (1, 'store-1'), (2, 'store-2')"))
    yield
    async with owner_engine.begin() as conn:
        for stmt in disable_tenant_rls("rls_probe"):
            await conn.execute(text(stmt))
        await conn.execute(text("DROP TABLE rls_probe"))


async def _notes(session) -> list[str]:
    return list(await session.scalars(text("SELECT note FROM rls_probe ORDER BY note")))


async def test_unbound_session_sees_nothing(probe: None) -> None:
    async with SessionLocal() as session:
        assert await _notes(session) == []


async def test_bound_session_sees_only_its_store(probe: None) -> None:
    async with SessionLocal() as session:
        await bind_tenant(session, 1)
        assert await _notes(session) == ["store-1"]


async def test_binding_survives_commit(probe: None) -> None:
    """db-layer functions commit; the next transaction must still be scoped."""
    async with SessionLocal() as session:
        await bind_tenant(session, 2)
        assert await _notes(session) == ["store-2"]
        await session.commit()
        assert await _notes(session) == ["store-2"]
        await session.rollback()
        assert await _notes(session) == ["store-2"]


async def test_binding_does_not_leak_to_the_next_request(probe: None) -> None:
    """Same pooled connection, next session: the transaction-local setting is gone."""
    async with SessionLocal() as first:
        await bind_tenant(first, 1)
        assert await _notes(first) == ["store-1"]
        pid = await first.scalar(text("SELECT pg_backend_pid()"))
    async with SessionLocal() as second:
        assert await second.scalar(text("SELECT pg_backend_pid()")) == pid  # really the same connection
        assert await _notes(second) == []


async def test_cannot_write_into_another_store(probe: None) -> None:
    async with SessionLocal() as session:
        await bind_tenant(session, 1)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(text("INSERT INTO rls_probe VALUES (2, 'sneaky')"))
        await session.rollback()


async def test_cannot_move_a_row_to_another_store(probe: None) -> None:
    async with SessionLocal() as session:
        await bind_tenant(session, 1)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(text("UPDATE rls_probe SET tenant_id = 2"))
        await session.rollback()


async def test_bind_tenant_ends_the_unscoped_transaction(probe: None) -> None:
    """A tenant lookup usually runs before binding; the scope must apply right after."""
    async with SessionLocal() as session:
        assert await _notes(session) == []  # opens a transaction without a tenant
        await bind_tenant(session, 1)
        assert await _notes(session) == ["store-1"]


async def test_bind_tenant_refuses_to_switch_store(probe: None) -> None:
    async with SessionLocal() as session:
        await bind_tenant(session, 1)
        await bind_tenant(session, 1)  # same store again is fine
        with pytest.raises(RuntimeError, match="already bound"):
            await bind_tenant(session, 2)


# Tables that carry tenant_id but are platform-level ON PURPOSE (see their models).
PLATFORM_TABLES_WITH_TENANT_ID = {"memberships", "jobs"}


async def test_every_store_table_has_rls(owner_engine: AsyncEngine) -> None:
    """A new table with tenant_id and no RLS fails here, not in production."""
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity,
                       EXISTS (SELECT 1 FROM pg_policies p
                               WHERE p.tablename = c.relname AND p.policyname = 'tenant_isolation')
                FROM pg_class c
                JOIN information_schema.columns col
                  ON col.table_name = c.relname AND col.column_name = 'tenant_id'
                WHERE c.relkind = 'r' AND col.table_schema = 'public'
                """
            )
        )
        found = {name: (rls, policy) for name, rls, policy in rows}
    store_tables = set(found) - PLATFORM_TABLES_WITH_TENANT_ID
    assert {"inventory_items", "inventory_imports", "customers", "orders", "order_items"} <= store_tables
    assert {name: found[name] for name in store_tables} == dict.fromkeys(store_tables, (True, True))
