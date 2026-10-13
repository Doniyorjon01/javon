"""delivery settings, customers, orders, order items

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12 14:00:00+05:00

tenants  pickup / delivery settings (money in tiyin) and order_seq, the per-store
         order counter. Existing stores: pickup on, delivery off.
customers, orders, order_items  belong to a store: RLS on all three.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from database.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("customers", "orders", "order_items")
PHONE_E164 = r"~ '^\+[1-9][0-9]{6,14}$'"


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
    # --- tenants: delivery settings and the order counter -------------------------------
    op.add_column(
        "tenants", sa.Column("pickup_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.add_column(
        "tenants",
        sa.Column("delivery_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "tenants", sa.Column("delivery_fee", sa.BigInteger(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column("tenants", sa.Column("free_delivery_from", sa.BigInteger(), nullable=True))
    op.add_column("tenants", sa.Column("delivery_area", sa.String(length=300), nullable=True))
    op.add_column(
        "tenants", sa.Column("order_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_tenants_some_fulfilment"), "tenants", "pickup_enabled OR delivery_enabled"
    )
    op.create_check_constraint(op.f("ck_tenants_delivery_fee_not_negative"), "tenants", "delivery_fee >= 0")
    op.create_check_constraint(
        op.f("ck_tenants_free_delivery_from_positive"), "tenants", "free_delivery_from > 0"
    )
    op.create_check_constraint(op.f("ck_tenants_order_seq_not_negative"), "tenants", "order_seq >= 0")

    # --- customers ---------------------------------------------------------------------
    op.create_table(
        "customers",
        *_base_columns(),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("phone", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        _tenant_fk("customers"),
        sa.CheckConstraint(f"phone {PHONE_E164}", name=op.f("ck_customers_phone_e164")),
    )
    op.create_index("uq_customers_tenant_phone", "customers", ["tenant_id", "phone"], unique=True)

    # --- orders ------------------------------------------------------------------------
    op.create_table(
        "orders",
        *_base_columns(),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("channel", sa.String(length=16), server_default="web", nullable=False),
        sa.Column("customer_name", sa.String(length=80), nullable=False),
        sa.Column("customer_phone", sa.String(length=16), nullable=False),
        sa.Column("delivery_type", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("subtotal", sa.BigInteger(), nullable=False),
        sa.Column("delivery_fee", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("payment_method", sa.String(length=16), nullable=False),
        sa.Column("payment_status", sa.String(length=16), server_default="unpaid", nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        _tenant_fk("orders"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'accepted', 'shipping', 'completed', 'cancelled')",
            name=op.f("ck_orders_order_status"),
        ),
        sa.CheckConstraint("channel IN ('web', 'telegram')", name=op.f("ck_orders_order_channel")),
        sa.CheckConstraint(
            "delivery_type IN ('pickup', 'delivery')", name=op.f("ck_orders_order_delivery_type")
        ),
        sa.CheckConstraint("payment_method IN ('cash')", name=op.f("ck_orders_order_payment_method")),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'paid')", name=op.f("ck_orders_order_payment_status")
        ),
        sa.CheckConstraint("number > 0", name=op.f("ck_orders_number_positive")),
        sa.CheckConstraint(f"customer_phone {PHONE_E164}", name=op.f("ck_orders_customer_phone_e164")),
        sa.CheckConstraint(
            "delivery_type = 'pickup' OR address IS NOT NULL", name=op.f("ck_orders_delivery_has_address")
        ),
        sa.CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name=op.f("ck_orders_location_pair")),
        sa.CheckConstraint(
            "subtotal >= 0 AND delivery_fee >= 0 AND total = subtotal + delivery_fee",
            name=op.f("ck_orders_money_adds_up"),
        ),
        sa.CheckConstraint(
            "status <> 'cancelled' OR cancelled_at IS NOT NULL", name=op.f("ck_orders_cancelled_has_time")
        ),
    )
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"])
    op.create_index("ix_orders_tenant_created", "orders", ["tenant_id", "created_at"])
    op.create_index("ix_orders_tenant_status_created", "orders", ["tenant_id", "status", "created_at"])
    op.create_index(
        "uq_orders_tenant_idempotency_key", "orders", ["tenant_id", "idempotency_key"], unique=True
    )
    op.create_index("uq_orders_tenant_number", "orders", ["tenant_id", "number"], unique=True)

    # --- order_items ---------------------------------------------------------------------
    op.create_table(
        "order_items",
        *_base_columns(),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("isbn13", sa.String(length=13), nullable=True),
        sa.Column("mxik_code", sa.String(length=17), nullable=True),
        sa.Column("package_code", sa.String(length=20), nullable=True),
        sa.Column("unit_price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        _tenant_fk("order_items"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_order_items_order_id_orders"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_order_items_book_id_books"), ondelete="RESTRICT"
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total = unit_price * quantity",
            name=op.f("ck_order_items_line_total_matches"),
        ),
    )
    op.create_index(op.f("ix_order_items_book_id"), "order_items", ["book_id"])
    op.create_index("uq_order_items_order_book", "order_items", ["order_id", "book_id"], unique=True)

    for table in TENANT_TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("customers")

    for name in (
        "order_seq_not_negative",
        "free_delivery_from_positive",
        "delivery_fee_not_negative",
        "some_fulfilment",
    ):
        op.drop_constraint(op.f(f"ck_tenants_{name}"), "tenants", type_="check")
    for column in (
        "order_seq",
        "delivery_area",
        "free_delivery_from",
        "delivery_fee",
        "delivery_enabled",
        "pickup_enabled",
    ):
        op.drop_column("tenants", column)
