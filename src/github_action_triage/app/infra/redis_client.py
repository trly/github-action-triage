import logging
from typing import Optional

import redis
from redis import ConnectionPool, Redis

from github_action_triage.agent.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        _redis_client = Redis(connection_pool=pool)
        logger.info(f"Redis client initialized with URL: {settings.redis_url}")
    return _redis_client


def set_if_not_exists(key: str, value: str, ttl_seconds: int) -> bool:
    try:
        client = get_redis_client()
        result = client.set(key, value, nx=True, ex=ttl_seconds)
        return bool(result)
    except redis.RedisError as e:
        logger.error(f"Redis error during setnx for key {key}: {e}")
        raise


def set_expiry(key: str, ttl_seconds: int) -> bool:
    try:
        client = get_redis_client()
        result = client.expire(key, ttl_seconds)
        return bool(result)
    except redis.RedisError as e:
        logger.error(f"Redis error during expire for key {key}: {e}")
        raise
