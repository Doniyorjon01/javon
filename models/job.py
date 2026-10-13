"""
Background jobs (and the outbox)
================================
A job is a row in `jobs`, written in the SAME transaction as the change that
needs it: an order and its "notify the store" job are committed together or
not at all, so a notification is never lost and never sent for an order that
was rolled back (the outbox pattern). workers/main.py picks queued jobs with
SELECT ... FOR UPDATE SKIP LOCKED, so several worker processes never take the
same job.

Why not arq: arq requires the redis client below version 6 and we use 8; a
table also gives the transactional enqueue that a Redis queue cannot.

Platform-level table (no RLS): the worker must see every store's jobs. It binds
its session to job.tenant_id before running the job, so the job itself works
under RLS like a request does. The payload holds ids only, never personal data.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.tenant import enum_check, str_enum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"  # gave up after max_attempts; last_error says why


class Job(Base):
    __tablename__ = "jobs"
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), server_default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("5"))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        enum_check("status", JobStatus, "job_status"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempts_range"),
        # The worker's "next job" query reads only this small index.
        Index("ix_jobs_queued", "run_after", "id", postgresql_where=text("status = 'queued'")),
        # Finding jobs stuck in "running" after a worker crash.
        Index("ix_jobs_running", "locked_at", postgresql_where=text("status = 'running'")),
        Index("ix_jobs_tenant_id", "tenant_id"),
    )
