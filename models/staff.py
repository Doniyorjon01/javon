"""
Staff invites
=============
The owner creates a link (APP_URL/taklif/<token>) and sends it to a colleague;
whoever opens it signed in with Telegram becomes the store's staff. A link works
once and for INVITE_TTL_DAYS (database/db_staff.py).

Only the SHA-256 of the token is stored, like session tokens: a database dump
does not hand out working invites. Platform-level table (no RLS): an invite is
looked up by its token before anyone knows which store it belongs to.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BaseModel


class StaffInvite(BaseModel):
    """is_active = False: revoked by the owner."""

    __tablename__ = "staff_invites"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The owner's list of open invites.
        Index(
            "ix_staff_invites_open",
            "tenant_id",
            "expires_at",
            postgresql_where=text("is_active AND accepted_at IS NULL"),
        ),
    )
