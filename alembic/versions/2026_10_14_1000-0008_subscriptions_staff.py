"""subscriptions, staff invites

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14 10:00:00+05:00

subscription_payments  payments the platform admin records by hand; voided, never
                       deleted. Platform-level (no RLS).
staff_invites          one-time links to join a store as staff; only the token's
                       SHA-256 is stored. Platform-level (no RLS): looked up by token.
tenants                paid_until (end of the last paid period), suspended_reason,
                       subscription_notice (last reminder sent to the owner).
platform_order_totals(since)
                       per-store order counts and sales since a moment, for the
                       platform admin. SECURITY DEFINER (runs as the schema owner,
                       so RLS does not hide other stores) and returns aggregates
                       only: no buyer data leaves it.
Existing stores keep their trial dates; nobody is closed by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PLATFORM_ORDER_TOTALS = """
CREATE FUNCTION platform_order_totals(since timestamptz)
RETURNS TABLE (tenant_id bigint, orders bigint, sales bigint, last_order_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT o.tenant_id,
           count(*),
           COALESCE(sum(o.total) FILTER (WHERE o.status <> 'cancelled'), 0)::bigint,
           max(o.created_at)
    FROM orders o
    WHERE o.created_at >= since
    GROUP BY o.tenant_id
$$
"""


def upgrade() -> None:
    op.create_table(
        "staff_invites",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", sa.BigInteger(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name=op.f("fk_staff_invites_accepted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_staff_invites_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_staff_invites_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_staff_invites_token_hash")),
    )
    op.create_index(
        "ix_staff_invites_open",
        "staff_invites",
        ["tenant_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("is_active AND accepted_at IS NULL"),
    )
    op.create_table(
        "subscription_payments",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("start", "standard", "pro", name="plan", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("months", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("recorded_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "plan IN ('start', 'standard', 'pro')", name=op.f("ck_subscription_payments_subscription_plan")
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_subscription_payments_amount_not_negative")),
        sa.CheckConstraint("months BETWEEN 1 AND 36", name=op.f("ck_subscription_payments_months_range")),
        sa.CheckConstraint("period_end > period_start", name=op.f("ck_subscription_payments_period_order")),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name=op.f("fk_subscription_payments_recorded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_subscription_payments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_payments")),
    )
    op.create_index(
        "ix_subscription_payments_tenant", "subscription_payments", ["tenant_id", "period_end"], unique=False
    )
    op.add_column("tenants", sa.Column("paid_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("suspended_reason", sa.String(length=300), nullable=True))
    op.add_column("tenants", sa.Column("subscription_notice", sa.String(length=40), nullable=True))
    op.execute(PLATFORM_ORDER_TOTALS)
    op.execute("REVOKE ALL ON FUNCTION platform_order_totals(timestamptz) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform_order_totals(timestamptz) TO javon_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform_order_totals(timestamptz)")
    op.drop_column("tenants", "subscription_notice")
    op.drop_column("tenants", "suspended_reason")
    op.drop_column("tenants", "paid_until")
    op.drop_index("ix_subscription_payments_tenant", table_name="subscription_payments")
    op.drop_table("subscription_payments")
    op.drop_index(
        "ix_staff_invites_open",
        table_name="staff_invites",
        postgresql_where=sa.text("is_active AND accepted_at IS NULL"),
    )
    op.drop_table("staff_invites")
