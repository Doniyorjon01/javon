"""
Background worker
=================
    python -m workers.main          (the `worker` service in docker-compose.yml)

Runs jobs from the `jobs` table (models/job.py): Excel imports, Telegram
notifications to stores and owners; plus periodic work (unpaid card orders,
subscription reminders, hourly clean-up). WORKER_CONCURRENCY lanes each take one job at a time;
several worker processes may run side by side (SKIP LOCKED keeps them apart).

Each job runs in its own session, bound to the job's store, so Row Level
Security applies exactly as in a request. A job that raises is retried with
exponential backoff (database/db_job.py) and marked failed after max_attempts;
the error text is kept in jobs.last_error and the traceback goes to the log.

SIGTERM (docker stop) lets running jobs finish, then exits.

Liveness: a heartbeat file proves the loop runs and the database answers
(workers/healthcheck.py, the container healthcheck).
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_job, db_order, db_tenant
from database.config import SessionLocal, bind_tenant, engine
from database.db_job import JobKind
from middleware import request_id_var
from models.job import Job
from utils.log import configure_logging
from utils.sentry import init_sentry
from workers import inventory_import, notifications, subscriptions
from workers.healthcheck import HEARTBEAT_FILE, HEARTBEAT_INTERVAL_S

logger = logging.getLogger("javon.worker")

Handler = Callable[[AsyncSession, Job], Awaitable[None]]

HANDLERS: dict[str, Handler] = {
    JobKind.INVENTORY_IMPORT: inventory_import.run,
    JobKind.ORDER_CREATED: notifications.order_created,
    JobKind.ORDER_STATUS_CHANGED: notifications.order_status_changed,
    JobKind.PAYMENT_PROOF_RECEIVED: notifications.payment_proof_received,
    JobKind.PAYMENT_REVIEWED: notifications.payment_reviewed,
    JobKind.OWNER_NOTICE: subscriptions.owner_notice,
}

STALE_CHECK_INTERVAL_S = 60.0
PERIODIC_INTERVAL_S = 300.0
CLEANUP_INTERVAL_S = 3600.0


class UnknownJobKindError(Exception):
    pass


async def run_job(job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    if handler is None:
        raise UnknownJobKindError(job.kind)
    async with SessionLocal() as db:
        if job.tenant_id is not None:
            await bind_tenant(db, job.tenant_id)
        await handler(db, job)


async def process_one() -> bool:
    """Run one due job. False when the queue is empty."""
    async with SessionLocal() as db:
        job = await db_job.claim_next(db)
    if job is None:
        return False

    token = request_id_var.set(f"job-{job.id}")
    log_extra = {"job_id": job.id, "kind": job.kind, "tenant_id": job.tenant_id, "attempt": job.attempts}
    try:
        await run_job(job)
    except Exception as exc:
        logger.exception("Job failed", extra=log_extra)
        async with SessionLocal() as db:
            new_status = await db_job.fail(
                db, job.id, f"{type(exc).__name__}: {exc}", permanent=isinstance(exc, UnknownJobKindError)
            )
        logger.info(
            "Job will %s", "be retried" if new_status == "queued" else "not be retried", extra=log_extra
        )
    else:
        async with SessionLocal() as db:
            await db_job.finish(db, job.id)
        logger.info("Job done", extra=log_extra)
    finally:
        request_id_var.reset(token)
    return True


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def _lane(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            busy = await process_one()
        except Exception:  # the database is down, say: wait and try again
            logger.exception("Worker loop error")
            busy = False
        if not busy:
            await _sleep_or_stop(stop, settings.WORKER_POLL_INTERVAL_S)


async def _reaper(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with SessionLocal() as db:
                count = await db_job.requeue_stale(db)
            if count:
                logger.warning("Requeued stale jobs", extra={"count": count})
        except Exception:
            logger.exception("Stale job check failed")
        await _sleep_or_stop(stop, STALE_CHECK_INTERVAL_S)


async def beat() -> None:
    """Touch the heartbeat file if the database answers; raises otherwise."""
    async with SessionLocal() as db:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=HEARTBEAT_INTERVAL_S)
    await asyncio.to_thread(HEARTBEAT_FILE.touch)


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await beat()
        except Exception:  # no beat: the healthcheck turns unhealthy after a few of these
            logger.exception("Heartbeat failed")
        await _sleep_or_stop(stop, HEARTBEAT_INTERVAL_S)


async def run_periodic_tasks(*, cleanup: bool = False) -> None:
    """
    Every PERIODIC_INTERVAL_S: work that no request triggers. Subscription
    reminders over all stores (platform table), then per store under RLS:
    unpaid card orders; with `cleanup` (hourly) also old import files, and the
    platform tables' clean-up.
    """
    try:
        async with SessionLocal() as db:
            queued = await subscriptions.scan_reminders(db)
        if queued:
            logger.info("Subscription reminders queued", extra={"count": queued})
    except Exception:
        logger.exception("Subscription reminder scan failed")
    if cleanup:
        try:
            async with SessionLocal() as db:
                removed = await subscriptions.cleanup(db)
            logger.info("Clean-up done", extra=removed)
        except Exception:
            logger.exception("Clean-up failed")

    async with SessionLocal() as db:
        tenant_ids = await db_tenant.get_active_tenant_ids(db)
    for tenant_id in tenant_ids:
        try:
            async with SessionLocal() as db:
                await bind_tenant(db, tenant_id)
                await db_order.cancel_unpaid_card_orders(db, tenant_id)
                if cleanup:
                    await subscriptions.cleanup_store(db, tenant_id)
        except Exception:
            logger.exception("Periodic task failed", extra={"tenant_id": tenant_id})


async def _periodic(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    last_cleanup = -CLEANUP_INTERVAL_S
    while not stop.is_set():
        cleanup = loop.time() - last_cleanup >= CLEANUP_INTERVAL_S
        if cleanup:
            last_cleanup = loop.time()
        try:
            await run_periodic_tasks(cleanup=cleanup)
        except Exception:
            logger.exception("Periodic tasks failed")
        await _sleep_or_stop(stop, PERIODIC_INTERVAL_S)


async def serve(stop: asyncio.Event) -> None:
    lanes = [asyncio.create_task(_lane(stop)) for _ in range(settings.WORKER_CONCURRENCY)]
    others = [
        asyncio.create_task(_reaper(stop)),
        asyncio.create_task(_periodic(stop)),
        asyncio.create_task(_heartbeat(stop)),
    ]
    logger.info("Worker started", extra={"lanes": len(lanes)})
    await asyncio.gather(*lanes, *others)
    await notifications.get_client().aclose()
    await engine.dispose()
    logger.info("Worker stopped")


def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    init_sentry("worker")
    # A restarted container keeps its /tmp: never report healthy on the last run's beat.
    HEARTBEAT_FILE.unlink(missing_ok=True)

    async def _run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await serve(stop)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
