"""jobs queue, store inventory, inventory imports

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 13:00:00+05:00

jobs               background work and the outbox (models/job.py). Platform-level,
                   no RLS: the worker sees every store's jobs.
inventory_items    a store's price and stock for a catalog book. RLS.
inventory_imports  an uploaded Excel file and its report. RLS.
books.submitted_via  manual / import: pending books are limited per source.
                   Existing store submissions were all made by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from database.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("inventory_items", "inventory_imports")


def _base_columns() -> list[sa.Column]:
    """models/base.py BaseModel columns."""
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{table}_tenant_id_tenants"), ondelete="RESTRICT"
    )


def upgrade() -> None:
    # --- jobs ------------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default=sa.text("5"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_jobs_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_jobs_job_status")
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name=op.f("ck_jobs_attempts_range")),
    )
    op.create_index(
        "ix_jobs_queued", "jobs", ["run_after", "id"], postgresql_where=sa.text("status = 'queued'")
    )
    op.create_index("ix_jobs_running", "jobs", ["locked_at"], postgresql_where=sa.text("status = 'running'"))
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])

    # --- inventory_items -----------------------------------------------------------
    op.create_table(
        "inventory_items",
        *_base_columns(),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_items")),
        _tenant_fk("inventory_items"),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_inventory_items_book_id_books"), ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "price >= 0 AND price <= 100000000000", name=op.f("ck_inventory_items_price_range")
        ),
        sa.CheckConstraint(
            "quantity >= 0 AND quantity <= 1000000", name=op.f("ck_inventory_items_quantity_range")
        ),
    )
    op.create_index(op.f("ix_inventory_items_book_id"), "inventory_items", ["book_id"])
    op.create_index("ix_inventory_items_tenant_updated", "inventory_items", ["tenant_id", "updated_at"])
    op.create_index(
        "uq_inventory_items_tenant_book_live",
        "inventory_items",
        ["tenant_id", "book_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- inventory_imports -----------------------------------------------------------
    op.create_table(
        "inventory_imports",
        *_base_columns(),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
        sa.Column("lang", sa.String(length=2), server_default="uz", nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_imports")),
        _tenant_fk("inventory_imports"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_inventory_imports_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_inventory_imports_import_status"),
        ),
        sa.CheckConstraint(
            "processed_rows >= 0 AND total_rows >= 0", name=op.f("ck_inventory_imports_row_counts")
        ),
    )
    op.create_index("ix_inventory_imports_tenant_created", "inventory_imports", ["tenant_id", "created_at"])

    for table in TENANT_TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)

    # --- books.submitted_via ---------------------------------------------------------
    op.add_column("books", sa.Column("submitted_via", sa.String(length=16), nullable=True))
    op.execute("UPDATE books SET submitted_via = 'manual' WHERE created_by_tenant_id IS NOT NULL")
    op.create_check_constraint(
        op.f("ck_books_book_submitted_via"), "books", "submitted_via IN ('manual', 'import')"
    )
    op.create_check_constraint(
        op.f("ck_books_submitted_via_with_tenant"),
        "books",
        "(created_by_tenant_id IS NULL) = (submitted_via IS NULL)",
    )
    op.drop_index("ix_books_pending", table_name="books")
    op.create_index(
        "ix_books_pending",
        "books",
        ["created_by_tenant_id", "submitted_via", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_books_pending", table_name="books")
    op.create_index(
        "ix_books_pending",
        "books",
        ["created_by_tenant_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_constraint(op.f("ck_books_submitted_via_with_tenant"), "books", type_="check")
    op.drop_constraint(op.f("ck_books_book_submitted_via"), "books", type_="check")
    op.drop_column("books", "submitted_via")

    for table in TENANT_TABLES:
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
    op.drop_table("inventory_imports")
    op.drop_table("inventory_items")
    op.drop_table("jobs")
