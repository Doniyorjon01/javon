"""store bots, card-transfer payments

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13 17:00:00+05:00

telegram_bots  one bot per store, token encrypted. Platform-level (no RLS): a
               webhook names the bot before the store is known.
tenants        cash_enabled / card_transfer_enabled, the store's card number and holder.
orders         payment method card_transfer, status awaiting_confirmation, the
               receipt key, the staff's note and paid_at. Paid cash orders get
               paid_at = completed_at.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.create_table(
        "telegram_bots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("group_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("group_title", sa.String(length=255), nullable=True),
        sa.Column("polling_offset", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_bots")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_telegram_bots_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_telegram_bots_tenant_id")),
        sa.UniqueConstraint("bot_user_id", name=op.f("uq_telegram_bots_bot_user_id")),
        sa.CheckConstraint("status IN ('active', 'broken')", name=op.f("ck_telegram_bots_bot_status")),
        sa.CheckConstraint(
            "char_length(webhook_secret) >= 32", name=op.f("ck_telegram_bots_webhook_secret_length")
        ),
    )

    # --- tenants: payment options ------------------------------------------------
    op.add_column(
        "tenants", sa.Column("cash_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.add_column(
        "tenants",
        sa.Column("card_transfer_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("tenants", sa.Column("card_number", sa.String(length=16), nullable=True))
    op.add_column("tenants", sa.Column("card_holder", sa.String(length=80), nullable=True))
    op.create_check_constraint(
        op.f("ck_tenants_some_payment"), "tenants", "cash_enabled OR card_transfer_enabled"
    )
    op.create_check_constraint(
        op.f("ck_tenants_card_number_format"), "tenants", "card_number ~ '^[0-9]{16}$'"
    )
    op.create_check_constraint(
        op.f("ck_tenants_card_transfer_has_card"),
        "tenants",
        "NOT card_transfer_enabled OR (card_number IS NOT NULL AND card_holder IS NOT NULL)",
    )

    # --- orders: card transfer -------------------------------------------------------
    op.add_column("orders", sa.Column("payment_proof_key", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("payment_note", sa.String(length=300), nullable=True))
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE orders SET paid_at = coalesce(completed_at, updated_at) WHERE payment_status = 'paid'")
    _replace_check("orders", "order_payment_method", "payment_method IN ('cash', 'card_transfer')")
    _replace_check("orders", "order_payment_status", "payment_status IN ('unpaid', 'under_review', 'paid')")
    op.create_check_constraint(
        op.f("ck_orders_paid_has_time"), "orders", "payment_status <> 'paid' OR paid_at IS NOT NULL"
    )
    # Unpaid card-transfer orders, for the worker's "cancel after CARD_TRANSFER_HOLD_HOURS".
    op.create_index(
        "ix_orders_card_transfer_unpaid",
        "orders",
        ["tenant_id", "updated_at"],
        postgresql_where=sa.text(
            "payment_method = 'card_transfer' AND payment_status = 'unpaid' AND status IN ('new', 'accepted')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_card_transfer_unpaid", table_name="orders")
    op.drop_constraint(op.f("ck_orders_paid_has_time"), "orders", type_="check")
    # Card-transfer orders cannot be represented in the old schema.
    op.execute("UPDATE orders SET payment_method = 'cash' WHERE payment_method = 'card_transfer'")
    op.execute("UPDATE orders SET payment_status = 'unpaid' WHERE payment_status = 'under_review'")
    _replace_check("orders", "order_payment_method", "payment_method IN ('cash')")
    _replace_check("orders", "order_payment_status", "payment_status IN ('unpaid', 'paid')")
    for column in ("paid_at", "payment_note", "payment_proof_key"):
        op.drop_column("orders", column)

    for name in ("card_transfer_has_card", "card_number_format", "some_payment"):
        op.drop_constraint(op.f(f"ck_tenants_{name}"), "tenants", type_="check")
    for column in ("card_holder", "card_number", "card_transfer_enabled", "cash_enabled"):
        op.drop_column("tenants", column)

    op.drop_table("telegram_bots")
