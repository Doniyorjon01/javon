"""
Rate limiting (Redis, fixed window)
===================================
    allowed = await hit(redis, f"order:{tenant_id}:{ip}", limit=10, window_s=600)

Fixed windows are simple and good enough for spam guards. Fails OPEN: if Redis
is down, requests are allowed (and a warning is logged): losing a real buyer's
order is worse than letting some spam through for a few minutes.
"""

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

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
