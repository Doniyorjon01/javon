"""
Health checks
=============
    GET /health        liveness  — the process answers. Docker restarts it if not.
    GET /health/ready  readiness — PostgreSQL and Redis answer within 2 s.
                       Uptime monitoring watches this one.

Failure reasons go to the log, never to the response body.
"""

import asyncio
import logging
from collections.abc import Awaitable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.config import get_pg_db

router = APIRouter(prefix="/health", tags=["health"])

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_S = 2.0


async def _check(name: str, probe: Awaitable[object]) -> str:
    try:
        await asyncio.wait_for(probe, timeout=CHECK_TIMEOUT_S)
    except Exception:
        logger.warning("Readiness check failed: %s", name, exc_info=True)
        return "fail"
    return "ok"


@router.get("")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request, db: AsyncSession = Depends(get_pg_db)) -> JSONResponse:
    checks = {
        "database": await _check("database", db.execute(text("SELECT 1"))),
        "redis": await _check("redis", request.app.state.redis.ping()),
    }
    healthy = all(result == "ok" for result in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "fail", "checks": checks},
    )
