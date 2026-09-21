import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request

from app.config import settings


def verify_api_key(x_api_key: str = Header(default=None)) -> None:
    """Require a valid API key when authentication is enabled."""
    if not settings.auth_enabled:
        return
    if not x_api_key or x_api_key not in settings.API_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide it in the X-API-Key header.",
        )


class _SlidingWindowLimiter:
    """In-process sliding-window rate limiter keyed by client IP."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) < limit:
            hits.append(now)
            return True
        return False

    def retry_after(self, key: str, window: int) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(0, int(window - (time.monotonic() - hits[0])) + 1)


_limiter = _SlidingWindowLimiter()


def rate_limit(route: str) -> list:
    limit, window = settings.RATE_LIMITS.get(route, (10, 60))

    def dependency(request: Request) -> None:
        client_key = f"{request.client.host if request.client else 'unknown'}:{route}"
        if not _limiter.allow(client_key, limit, window):
            retry_after = _limiter.retry_after(client_key, window)
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait before trying again.",
                headers={"Retry-After": str(retry_after)},
            )

    return [Depends(dependency)]


def api_key_dependency() -> list:
    return [Depends(verify_api_key)]