"""author and publisher alphabet, import quantity mode, store pause

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20 10:00:00+05:00

authors, publishers  `script` (latn / cyrl / other); unique (search_key, script)
                     instead of (search_key): "Абдулла Қодирий" is no longer
                     stored as "Abdulla Qodiriy". Existing rows get their script
                     from their name. Books already linked to the other spelling
                     keep it (the platform admin can fix a book's authors).
inventory_imports    quantity_mode: add (default: "2 arrived") or set (stocktake).
tenants              paused_at: the owner closed the storefront for a while.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCRIPT = sa.Enum("latn", "cyrl", "other", name="bookscript", native_enum=False, length=16)
CYRILLIC = "А-Яа-яЁёЎўҚқҒғҲҳІіЇїЄєЭэ"  # noqa: RUF001 — Cyrillic letters on purpose


def _script_sql(table: str) -> str:
    """The same rule as utils/translit.detect_script, by letter counts."""
    latin = "length(regexp_replace(name, '[^A-Za-z]', '', 'g'))"
    cyrillic = f"length(regexp_replace(name, '[^{CYRILLIC}]', '', 'g'))"
    return (  # table is one of two constants
        f"UPDATE {table} SET script = CASE "  # noqa: S608
        f"WHEN {cyrillic} > {latin} THEN 'cyrl' WHEN {latin} > {cyrillic} THEN 'latn' ELSE 'other' END"
    )


def upgrade() -> None:
    for table in ("authors", "publishers"):
        op.add_column(table, sa.Column("script", SCRIPT, server_default="latn", nullable=False))
        op.execute(_script_sql(table))
        op.create_check_constraint(
            op.f(f"ck_{table}_{table[:-1]}_script"), table, "script IN ('latn', 'cyrl', 'other')"
        )
        op.drop_constraint(op.f(f"uq_{table}_search_key"), table, type_="unique")
        op.create_unique_constraint(f"uq_{table}_search_key_script", table, ["search_key", "script"])

    op.add_column(
        "inventory_imports",
        sa.Column(
            "quantity_mode",
            sa.Enum("add", "set", name="quantitymode", native_enum=False, length=16),
            server_default="add",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_inventory_imports_import_quantity_mode"),
        "inventory_imports",
        "quantity_mode IN ('add', 'set')",
    )
    op.add_column("tenants", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "paused_at")
    op.drop_constraint(op.f("ck_inventory_imports_import_quantity_mode"), "inventory_imports", type_="check")
    op.drop_column("inventory_imports", "quantity_mode")

    # Back to one row per search key: links move to the oldest spelling.
    op.execute(
        "UPDATE book_authors ba SET author_id = keep.id "
        "FROM authors a JOIN (SELECT search_key, min(id) AS id FROM authors GROUP BY search_key) keep "
        "ON keep.search_key = a.search_key WHERE ba.author_id = a.id AND a.id <> keep.id"
    )
    op.execute(
        "UPDATE books b SET publisher_id = keep.id "
        "FROM publishers p JOIN (SELECT search_key, min(id) AS id FROM publishers GROUP BY search_key) keep "
        "ON keep.search_key = p.search_key WHERE b.publisher_id = p.id AND p.id <> keep.id"
    )
    for table in ("authors", "publishers"):
        keep = f"(SELECT search_key, min(id) AS id FROM {table} GROUP BY search_key) keep"  # noqa: S608
        op.execute(
            f"DELETE FROM {table} t USING {keep} "  # noqa: S608 — table is one of two constants
            "WHERE t.search_key = keep.search_key AND t.id <> keep.id"
        )
        op.drop_constraint(f"uq_{table}_search_key_script", table, type_="unique")
        op.create_unique_constraint(op.f(f"uq_{table}_search_key"), table, ["search_key"])
        op.drop_constraint(op.f(f"ck_{table}_{table[:-1]}_script"), table, type_="check")
        op.drop_column(table, "script")
