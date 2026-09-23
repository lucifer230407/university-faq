import logging
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """
    Resolve the real client IP.

    Only trusts X-Forwarded-For when the direct peer is a configured proxy
    (TRUSTED_PROXY_IPS). Otherwise spoofed headers are ignored and the socket
    address is used.
    """
    peer = request.client.host if request.client else "unknown"
    if peer in settings.trusted_proxy_ips:
        fwd = request.headers.get("X-Forwarded-For", "")
        first = fwd.split(",")[0].strip()
        if first:
            return first
    return peer


def verify_api_key(x_api_key: str = Header(default=None)) -> None:
    """Require a valid API key when authentication is enabled."""
    if not settings.auth_enabled:
        return
    if not x_api_key or x_api_key not in settings.api_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide it in the X-API-Key header.",
        )


class _SlidingWindowLimiter:
    """In-process sliding-window rate limiter keyed by client."""
    #: expiry in seconds; buckets this old are pruned on access.
    STALE_AFTER = 600

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str, window: int) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if hits and time.monotonic() - max(hits) > self.STALE_AFTER:
            self._hits.pop(key, None)

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        self._prune(key, window)
        hits = self._hits[key]
        if len(hits) < limit:
            hits.append(now)
            return True
        return False

    def retry_after(self, key: str, window: int) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(0, int(window - (time.monotonic() - hits[0])) + 1)


class _RedisSlidingWindowLimiter:
    """Redis-backed sliding-window limiter using a sorted set of hit timestamps."""

    def __init__(self, redis):
        self._r = redis

    @staticmethod
    def _key(route: str) -> str:
        return f"rate:{route}"

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        r = self._r
        bucket = self._key(key)

        def _exec(pipe):
            pipe.zremrangebyscore(bucket, 0, now - window)
            rank = pipe.zcard(bucket)
            if rank < limit:
                pipe.zadd(bucket, {str(now): now})
                pipe.expire(bucket, window)
                return True
            return False

        try:
            return r.transaction(_exec, bucket)[0]
        except Exception as e:  # pragma: no cover - Redis outage fallback
            logger.warning("Redis rate limiter unavailable, allowing request: %s", e)
            return True

    def retry_after(self, key: str, window: int) -> int:  # pragma: no cover
        try:
            now = time.monotonic()
            oldest = self._r.zrange(self._key(key), 0, 0, withscores=True)
            if not oldest:
                return 0
            return max(0, int(window - (now - oldest[0][1])) + 1)
        except Exception:
            return window


if settings.REDIS_URL and settings.REDIS_URL.strip():
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)
        _limiter = _RedisSlidingWindowLimiter(_redis_client)
        logger.info("Rate limiter backed by Redis at %s", settings.REDIS_URL)
    except Exception as e:  # pragma: no cover
        logger.error("Failed to init Redis limiter, falling back to memory: %s", e)
        _limiter = _SlidingWindowLimiter()
else:
    _limiter = _SlidingWindowLimiter()
    logger.info("Rate limiter backed by in-process memory")


def rate_limit(route: str) -> list:
    limit, window = settings.rate_limits.get(route, (10, 60))

    def dependency(request: Request) -> None:
        limiter_key = f"{client_ip(request)}:{route}"
        if not _limiter.allow(limiter_key, limit, window):
            retry_after = _limiter.retry_after(limiter_key, window)
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait before trying again.",
                headers={"Retry-After": str(retry_after)},
            )

    return [Depends(dependency)]


def api_key_dependency() -> list:
    # Auth is declared BEFORE the rate limiter in the dependency chain so
    # unauthenticated callers cannot consume a real user's rate-limit budget.
    return [Depends(verify_api_key)]