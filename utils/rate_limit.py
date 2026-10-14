"""
Rate limiting (Redis, fixed window)
===================================
    allowed = await hit(redis, f"order:{tenant_id}:{ip}", limit=10, window_s=600)

or, per IP for a whole route, the ip_rate_limit() dependency below.

Fixed windows are simple and good enough for spam guards. Fails OPEN: if Redis
is down, requests are allowed (and a warning is logged): losing a real buyer's
order is worse than letting some spam through for a few minutes.
"""

import logging
from collections.abc import Callable

from fastapi import Depends, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config import settings
from errors import generate_error
from translations import Msg
from utils.i18n import Lang, get_lang

logger = logging.getLogger(__name__)

PREFIX = "rl:"


async def hit(redis: Redis, key: str, *, limit: int, window_s: int) -> bool:
    """Count one request; True while the window still has room."""
    full_key = PREFIX + key
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(full_key)
            pipe.expire(full_key, window_s, nx=True)
            count, _ = await pipe.execute()
    except RedisError:
        logger.warning("Rate limiter unavailable, allowing request", exc_info=True)
        return True
    return int(count) <= limit


def client_ip(request: Request) -> str:
    """The caller's IP. Behind Caddy, uvicorn's --proxy-headers puts the real
    address here (X-Forwarded-For from Caddy only: port 8000 is never public)."""
    return request.client.host if request.client else "unknown"


def ip_rate_limit(scope: str, limit: Callable[[], int], window_s: Callable[[], int]) -> Callable:
    """
    A route dependency: at most limit() calls per window_s() seconds per IP for
    this scope, else 429 with Retry-After. The limits are read on each call, so
    settings changed in tests apply.

        @router.post("/auth/telegram", dependencies=[Depends(AUTH_LIMIT)])
    """

    async def dependency(request: Request, lang: Lang = Depends(get_lang)) -> None:
        redis: Redis | None = getattr(request.app.state, "redis", None)
        if redis is None:  # an app without its lifespan (some tests): fail open, as when Redis is down
            return
        window = window_s()
        if not await hit(redis, f"{scope}:{client_ip(request)}", limit=limit(), window_s=window):
            raise generate_error(
                Msg.TOO_MANY_REQUESTS,
                lang,
                status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(window)},
            )

    return dependency


# Shared limits. Sign-in: brute force and session flooding. Invites: guessing links.
AUTH_LIMIT = ip_rate_limit("auth", lambda: settings.AUTH_RATE_LIMIT, lambda: settings.AUTH_RATE_WINDOW_S)
INVITE_LIMIT = ip_rate_limit("invite", lambda: settings.AUTH_RATE_LIMIT, lambda: settings.AUTH_RATE_WINDOW_S)
# Receipt uploads: each one is an image conversion and a storage write.
PROOF_LIMIT = ip_rate_limit("proof", lambda: settings.PROOF_RATE_LIMIT, lambda: settings.ORDER_RATE_WINDOW_S)
