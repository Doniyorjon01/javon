"""
Alembic environment (async)
===========================
Runs as javon_owner (MIGRATION_DATABASE_URL), the role that owns the schema.
The API role (javon_app) only gets SELECT/INSERT/UPDATE/DELETE through the
default privileges set in scripts/postgres-init/01-roles.sh.

lock_timeout: a migration that cannot get its lock within 5 s fails instead of
queueing behind live traffic and freezing every request behind it.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from config import settings
from models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    if settings.MIGRATION_DATABASE_URL is None:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is not set. Migrations must run as the schema owner "
            "(javon_owner), not as the API role."
        )
    return str(settings.MIGRATION_DATABASE_URL)


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        _url(),
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s", "application_name": "javon-migrate"}},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
