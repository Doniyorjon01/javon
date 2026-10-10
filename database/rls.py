"""
Row Level Security helpers
==========================
Used from migrations, for every table that belongs to a store:

    from database.rls import enable_tenant_rls, disable_tenant_rls

    def upgrade():
        op.create_table("orders", ..., sa.Column("tenant_id", ...))
        for stmt in enable_tenant_rls("orders"):
            op.execute(stmt)

    def downgrade():
        for stmt in disable_tenant_rls("orders"):
            op.execute(stmt)
        op.drop_table("orders")

How it works: database/config.py writes the request's tenant into the
transaction-local setting `app.tenant_id`; the policy compares every row with it.
No tenant bound -> the setting is empty -> NULL -> the policy matches no rows.
The default is "see nothing", never "see everything".

NULLIF matters: once a pooled connection has used SET LOCAL, the setting exists
on that connection and reads back as '' (not NULL) in later transactions, and
''::bigint would raise instead of matching nothing.

Migrations call these functions, so their output must never change for an
existing policy. A different policy gets a new function.

This module must not import the app (config, models): migrations import it.
"""

import re

TENANT_SETTING = "app.tenant_id"
CURRENT_TENANT_SQL = f"NULLIF(current_setting('{TENANT_SETTING}', true), '')::bigint"
POLICY_NAME = "tenant_isolation"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check(table: str) -> str:
    if not _IDENTIFIER.match(table):
        raise ValueError(f"not a plain table name: {table!r}")
    return table


def enable_tenant_rls(table: str) -> list[str]:
    table = _check(table)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY {POLICY_NAME} ON {table} "
        f"USING (tenant_id = {CURRENT_TENANT_SQL}) "
        f"WITH CHECK (tenant_id = {CURRENT_TENANT_SQL})",
    ]


def disable_tenant_rls(table: str) -> list[str]:
    table = _check(table)
    return [
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]