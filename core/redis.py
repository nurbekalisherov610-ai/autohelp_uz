"""
AutoHelp.uz - Redis Connection Module
Manages Redis connections for FSM storage, caching, and pub/sub.

CRITICAL: Two separate connections are needed:
  1. FSM storage (decode_responses=False) — stores binary FSM data
  2. General cache (decode_responses=True) — for throttling, general use
"""
from redis.asyncio import Redis, ConnectionPool

from core.config import settings


# FSM storage connection (binary — required by aiogram RedisStorage)
_fsm_pool: ConnectionPool | None = None
_fsm_redis: Redis | None = None

# General cache connection (text)
_cache_pool: ConnectionPool | None = None
_cache_redis: Redis | None = None


async def get_fsm_redis() -> Redis:
    """Get Redis connection for FSM storage (binary mode)."""
    global _fsm_pool, _fsm_redis
    if _fsm_redis is None:
        _fsm_pool = ConnectionPool.from_url(
            settings.get_redis_url,
            max_connections=10,
            decode_responses=False,  # FSM needs binary
        )
        _fsm_redis = Redis(connection_pool=_fsm_pool)
    return _fsm_redis


async def get_redis() -> Redis:
    """Get Redis connection for general caching (text mode)."""
    global _cache_pool, _cache_redis
    if _cache_redis is None:
        _cache_pool = ConnectionPool.from_url(
            settings.get_redis_url,
            max_connections=20,
            decode_responses=True,
        )
        _cache_redis = Redis(connection_pool=_cache_pool)
    return _cache_redis


async def close_redis():
    """Close all Redis connections."""
    global _fsm_pool, _fsm_redis, _cache_pool, _cache_redis
    if _fsm_redis:
        await _fsm_redis.close()
        _fsm_redis = None
    if _fsm_pool:
        await _fsm_pool.disconnect()
        _fsm_pool = None
    if _cache_redis:
        await _cache_redis.close()
        _cache_redis = None
    if _cache_pool:
        await _cache_pool.disconnect()
        _cache_pool = None
