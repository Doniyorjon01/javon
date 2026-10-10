"""tenants, users, memberships

Revision ID: 0001
Revises:
Create Date: 2026-10-10 19:00:00+05:00

Platform-level tables, so no Row Level Security here (see models/tenant.py).
Enums are VARCHAR + CHECK (not native PG enums): adding a value later is a
plain ALTER of the CHECK, no type juggling.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHONE_E164 = r"phone ~ '^\+[1-9][0-9]{6,14}$'"


def _base_columns() -> list[sa.Column]:
    """models/base.py BaseModel columns."""
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    # The API may read which migration is applied, never change it.
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM javon_app")

    op.create_table(
        "users",
        *_base_columns(),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("language", sa.String(length=2), server_default="uz", nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
        sa.CheckConstraint(PHONE_E164, name=op.f("ck_users_phone_e164")),
        sa.CheckConstraint("language IN ('uz', 'ru', 'en')", name=op.f("ck_users_language_supported")),
    )

    op.create_table(
        "tenants",
        *_base_columns(),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="trial", nullable=False),
        sa.Column("plan", sa.String(length=16), server_default="standard", nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("theme", sa.String(length=32), server_default="classic", nullable=False),
        sa.Column("accent_color", sa.String(length=7), server_default="#2B3BD1", nullable=False),
        sa.Column("logo_key", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("working_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
        sa.Column("instagram_username", sa.String(length=30), nullable=True),
        sa.Column(
            "languages", sa.ARRAY(sa.String(length=2)), server_default=sa.text("'{uz}'"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        # Plain UNIQUE, not partial: a slug is never released, even after soft delete.
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
        sa.CheckConstraint(
            "slug ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 3 AND 40",
            name=op.f("ck_tenants_slug_format"),
        ),
        sa.CheckConstraint(
            "status IN ('trial', 'active', 'suspended')", name=op.f("ck_tenants_tenant_status")
        ),
        sa.CheckConstraint("plan IN ('start', 'standard', 'pro')", name=op.f("ck_tenants_tenant_plan")),
        sa.CheckConstraint("accent_color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_tenants_accent_color_hex")),
        sa.CheckConstraint(PHONE_E164, name=op.f("ck_tenants_phone_e164")),
        sa.CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name=op.f("ck_tenants_location_pair")),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
            name=op.f("ck_tenants_location_range"),
        ),
        sa.CheckConstraint("cardinality(languages) >= 1", name=op.f("ck_tenants_languages_not_empty")),
    )

    op.create_table(
        "memberships",
        *_base_columns(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_memberships_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.CheckConstraint("role IN ('owner', 'staff')", name=op.f("ck_memberships_member_role")),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"])
    # One active membership per person per store; its leading user_id also serves "my stores".
    op.create_index(
        "uq_memberships_user_tenant_active",
        "memberships",
        ["user_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    # Exactly one active owner per store.
    op.create_index(
        "uq_memberships_one_owner",
        "memberships",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_table("memberships")
    op.drop_table("tenants")
    op.drop_table("users")