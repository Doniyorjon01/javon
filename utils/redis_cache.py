"""
Redis helpers
=============
One async client per process, created in the FastAPI lifespan and kept on
app.state (never at module scope, never one per request). Routes get it with
`redis: Redis = Depends(get_redis)`.
"""

import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import Request
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def create_redis(url: str) -> Redis:
    return Redis.from_url(url, encoding="utf-8", decode_responses=True)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} is not JSON serializable")


async def get_from_redis(redis: Redis, key: str) -> Any | None:
    """A cache miss and a corrupt value both return None: the caller rebuilds."""
    value = await redis.get(key)
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.warning("Corrupt cache value, ignoring", extra={"cache_key": key})
        return None


async def set_to_redis(redis: Redis, key: str, value: Any, expire: int | None = 1800) -> Any:
    """`expire=None` keeps the key forever — use only for data you also invalidate explicitly."""
    await redis.set(key, json.dumps(value, default=_json_default, ensure_ascii=False), ex=expire)
    return value
