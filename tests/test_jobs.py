"""The jobs table and the worker loop (database/db_job.py, workers/main.py)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from database import db_job
from database.config import SessionLocal
from database.db_job import JobKind
from models import InventoryItem, Job, JobStatus
from tests.factories import make_book, make_item, make_tenant
from workers import main as worker

pytestmark = pytest.mark.db


async def _job(db: AsyncSession, job_id: int) -> Job:
    return await db.scalar(select(Job).where(Job.id == job_id), execution_options={"populate_existing": True})


async def test_enqueue_is_part_of_the_callers_transaction(db: AsyncSession) -> None:
    db_job.enqueue(db, JobKind.ORDER_CREATED, None, {"order_id": 1})
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(Job)) == 0

    db_job.enqueue(db, JobKind.ORDER_CREATED, None, {"order_id": 1})
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(Job)) == 1


async def test_two_workers_never_take_the_same_job(db: AsyncSession) -> None:
    for i in range(2):
        db_job.enqueue(db, JobKind.ORDER_CREATED, None, {"order_id": i})
    await db.commit()

    async with SessionLocal() as first, SessionLocal() as second:
        # The first worker holds its row lock (transaction still open) ...
        locked = await first.scalar(
            select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.id).limit(1).with_for_update()
        )
        # ... the second skips it and takes the next one instead of waiting.
        taken = await db_job.claim_next(second)
        assert taken is not None and taken.id != locked.id
        await first.rollback()


async def test_failure_backs_off_then_gives_up(db: AsyncSession) -> None:
    job = db_job.enqueue(db, JobKind.ORDER_CREATED, None, {}, max_attempts=2)
    await db.commit()

    async with SessionLocal() as session:
        claimed = await db_job.claim_next(session)
        assert claimed.attempts == 1
        assert await db_job.fail(session, claimed.id, "boom") == JobStatus.QUEUED
    retried = await _job(db, job.id)
    assert retried.run_after > datetime.now(UTC) + timedelta(seconds=5)  # not due yet
    async with SessionLocal() as session:
        assert await db_job.claim_next(session) is None

    await db.execute(update(Job).where(Job.id == job.id).values(run_after=func.now()))
    await db.commit()
    async with SessionLocal() as session:
        claimed = await db_job.claim_next(session)
        assert await db_job.fail(session, claimed.id, "boom again") == JobStatus.FAILED
    failed = await _job(db, job.id)
    assert (failed.status, failed.last_error, failed.finished_at is not None) == (
        JobStatus.FAILED,
        "boom again",
        True,
    )


def test_backoff_grows_and_is_capped() -> None:
    assert [db_job.backoff(n).total_seconds() for n in (1, 2, 3)] == [10, 20, 40]
    assert db_job.backoff(30) == db_job.MAX_BACKOFF


async def test_stale_running_jobs_are_requeued(db: AsyncSession) -> None:
    job = db_job.enqueue(db, JobKind.ORDER_CREATED, None, {})
    await db.commit()
    await db.execute(
        update(Job)
        .where(Job.id == job.id)
        .values(status=JobStatus.RUNNING, locked_at=text("now() - interval '1 hour'"))
    )
    await db.commit()
    async with SessionLocal() as session:
        assert await db_job.requeue_stale(session) == 1
    assert (await _job(db, job.id)).status == JobStatus.QUEUED


async def test_worker_runs_a_job_inside_its_store(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    store = await make_tenant(db, "varaq")
    other = await make_tenant(db, "boshqa")
    await make_item(store, await make_book(db, "Bir"))
    await make_item(other, await make_book(db, "Ikki"))
    seen: list[int] = []

    async def count_items(session: AsyncSession, job: Job) -> None:
        # RLS: the job's session sees only its own store's shelf, without any filter.
        seen.append(await session.scalar(select(func.count()).select_from(InventoryItem)))

    monkeypatch.setitem(worker.HANDLERS, "count_items", count_items)
    db.add(Job(kind="count_items", tenant_id=store.id, payload={}))
    await db.commit()

    assert await worker.process_one() is True
    assert seen == [1]
    assert await worker.process_one() is False  # queue empty
    assert (await db.scalar(select(Job.status))) == JobStatus.DONE


async def test_unknown_job_kind_fails_at_once(db: AsyncSession, owner_engine: AsyncEngine) -> None:
    db.add(Job(kind="no_such_kind", payload={}, max_attempts=5))
    await db.commit()
    assert await worker.process_one() is True
    job = await db.scalar(select(Job))
    assert (job.status, job.attempts) == (JobStatus.FAILED, 1)
    assert "no_such_kind" in job.last_error
