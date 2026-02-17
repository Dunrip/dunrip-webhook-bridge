import logging
import time
from typing import Protocol

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from errors import ErrorCode
from observability import new_request_id, request_id_ctx
from security import get_client_ip

try:
    from redis import RedisError
    from redis.asyncio import Redis
except ModuleNotFoundError:  # pragma: no cover - exercised in no-network envs
    Redis = None

    class RedisError(Exception):
        pass

logger = logging.getLogger(__name__)


class RateLimitBackend(Protocol):
    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        ...


class MemoryRateLimitBackend:
    def __init__(self) -> None:
        self._counters: dict[str, tuple[int, float]] = {}

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.time()
        count, expires_at = self._counters.get(key, (0, now + window_seconds))
        if now >= expires_at:
            count = 0
            expires_at = now + window_seconds
        count += 1
        self._counters[key] = (count, expires_at)
        retry_after = max(1, int(expires_at - now))
        return count, retry_after


class RedisRateLimitBackend:
    def __init__(self, redis_url: str, key_prefix: str) -> None:
        if Redis is None:
            raise RedisError("redis package is not installed")
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        namespaced_key = f"{self._key_prefix}:rate_limit:{key}"
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(namespaced_key)
            pipeline.expire(namespaced_key, window_seconds, nx=True)
            pipeline.ttl(namespaced_key)
            count, _, ttl = await pipeline.execute()
        retry_after = ttl if isinstance(ttl, int) and ttl > 0 else window_seconds
        return int(count), retry_after


class FallbackRateLimitBackend:
    def __init__(self, primary: RateLimitBackend, fallback: RateLimitBackend) -> None:
        self._primary = primary
        self._fallback = fallback
        self._warned = False

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            return await self._primary.increment(key, window_seconds)
        except RedisError as exc:
            if not self._warned:
                logger.warning(
                    "Redis rate limit backend unavailable, falling back to memory: %s",
                    exc,
                )
                self._warned = True
            return await self._fallback.increment(key, window_seconds)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        request.state.request_id = request_id

        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request_completed method=%s path=%s status=%d duration_ms=%.2f client_ip=%s",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
                get_client_ip(request),
            )
            request_id_ctx.reset(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        backend: RateLimitBackend,
        ip_limit_per_minute: int,
        token_limit_per_minute: int,
        admin_limit_per_minute: int,
    ) -> None:
        super().__init__(app)
        self._backend = backend
        self._ip_limit_per_minute = ip_limit_per_minute
        self._token_limit_per_minute = token_limit_per_minute
        self._admin_limit_per_minute = admin_limit_per_minute
        self._window_seconds = 60

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        is_webhook = path in {"/webhook/github", "/webhook/generic"}
        is_admin = path.startswith("/deliveries")

        if not is_webhook and not is_admin:
            return await call_next(request)

        ip = get_client_ip(request)
        checks: list[tuple[str, int, str]] = []

        if is_webhook and self._ip_limit_per_minute > 0:
            checks.append((f"ip:{path}:{ip}", self._ip_limit_per_minute, "Rate limit exceeded"))

        if (
            path == "/webhook/generic"
            and self._token_limit_per_minute > 0
            and request.headers.get("x-webhook-token")
        ):
            token = request.headers["x-webhook-token"]
            checks.append((f"token:{path}:{token}", self._token_limit_per_minute, "Rate limit exceeded"))

        if is_admin and self._admin_limit_per_minute > 0:
            checks.append((f"admin-ip:{path}:{ip}", self._admin_limit_per_minute, "Admin rate limit exceeded"))

        for key, limit, message in checks:
            count, retry_after = await self._backend.increment(key, self._window_seconds)
            if count > limit:
                request_id = getattr(request.state, "request_id", "-")
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": str(ErrorCode.RATE_LIMIT_EXCEEDED),
                        "message": message,
                        "request_id": request_id,
                    },
                    headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
                )

        return await call_next(request)


def create_rate_limit_backend() -> RateLimitBackend:
    memory_backend = MemoryRateLimitBackend()
    if settings.rate_limit_backend.lower() == "redis":
        try:
            return FallbackRateLimitBackend(
                primary=RedisRateLimitBackend(
                    redis_url=settings.redis_url,
                    key_prefix=settings.redis_key_prefix,
                ),
                fallback=memory_backend,
            )
        except RedisError as exc:
            logger.warning(
                "Redis rate limiter requested but unavailable, using memory backend: %s",
                exc,
            )
            return memory_backend
    return memory_backend
