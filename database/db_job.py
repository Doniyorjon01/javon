"""
Background jobs — database layer
================================
    db_job.enqueue(db, JobKind.ORDER_CREATED, tenant_id, {"order_id": order.id})
    await db.commit()          # the caller's commit: job and change land together

enqueue() only adds the row to the session; it never commits. That is the point:
the job exists if and only if the change that needs it was committed.

The worker side (claim / finish / fail / requeue) is used by workers/main.py.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.job import Job, JobStatus

# A job stuck in "running" this long belongs to a worker that died: run it again.
STALE_AFTER = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=1)


class JobKind(StrEnum):
    INVENTORY_IMPORT = "inventory_import"
    ORDER_CREATED = "order_created"
    ORDER_STATUS_CHANGED = "order_status_changed"
    PAYMENT_PROOF_RECEIVED = "payment_proof_received"
    PAYMENT_REVIEWED = "payment_reviewed"


def enqueue(
    db: AsyncSession,
    kind: JobKind,
    tenant_id: int | None,
    payload: dict[str, Any],
    *,
    max_attempts: int = 5,
) -> Job:
    job = Job(kind=kind.value, tenant_id=tenant_id, payload=payload, max_attempts=max_attempts)
    db.add(job)
    return job


# ----------------------------------------------------------------- worker side
async def claim_next(db: AsyncSession) -> Job | None:
    """
    Take the oldest due job and mark it running, in one short transaction.
    SKIP LOCKED: two workers never get the same job and never wait for each other.
    """
    job = await db.scalar(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= text("now()"))
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await db.rollback()
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.locked_at = datetime.now(UTC)
    await db.commit()
    return job


async def finish(db: AsyncSession, job_id: int) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status=JobStatus.DONE, finished_at=datetime.now(UTC), last_error=None)
    )
    await db.commit()


def backoff(attempts: int) -> timedelta:
    """10 s, 20 s, 40 s, ... capped at one hour."""
    return min(timedelta(seconds=10 * 2 ** max(attempts - 1, 0)), MAX_BACKOFF)


async def fail(db: AsyncSession, job_id: int, error: str, *, permanent: bool = False) -> JobStatus:
    """Retry later, or give up (after max_attempts, or at once when `permanent`)."""
    job = await db.get(Job, job_id, with_for_update=True)
    if job is None:  # pragma: no cover — rows are never deleted
        await db.rollback()
        return JobStatus.FAILED
    job.last_error = error[:2000]
    if permanent or job.attempts >= job.max_attempts:
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(UTC)
    else:
        job.status = JobStatus.QUEUED
        job.run_after = datetime.now(UTC) + backoff(job.attempts)
    await db.commit()
    return job.status


async def requeue_stale(db: AsyncSession) -> int:
    """Jobs left "running" by a crashed worker go back to the queue."""
    result = await db.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.locked_at < datetime.now(UTC) - STALE_AFTER)
        .values(status=JobStatus.QUEUED, run_after=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount or 0
