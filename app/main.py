"""FastAPI application entrypoint for the webhook bridge service.

This module wires app lifecycle, middleware, observability, routing, and
webhook endpoints for GitHub and generic payload forwarding.
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.replay import router as replay_router
from app.api.sandbox import router as sandbox_router
from app.api.webhooks import router as webhooks_router
from app.api.websocket import router as ws_router
from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.exceptions import WebhookError
from app.core.security import describe_admin_auth_mode
from app.infra.circuit_breaker import telegram_circuit
from app.infra.middleware import RateLimitMiddleware, RequestContextMiddleware, create_rate_limit_backend
from app.infra.storage import FallbackStorage, Redis, RedisError, create_storage_backend
from app.observability.observability import RequestContextFilter
from app.services.routing import destination_health_snapshot, load_routes

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestContextFilter())
logger = logging.getLogger(__name__)


# Re-export send_message so existing monkeypatch in tests still works
from app.services.tg_client import send_message as send_message  # noqa: E402, F401


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _error_response(request: Request, status_code: int, code: ErrorCode | str, message: str) -> JSONResponse:
    """Build a standardized JSON error response payload."""
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"error": str(code), "message": message, "request_id": rid},
        headers={"X-Request-ID": rid},
    )


def _initialize_app_state(app: FastAPI) -> None:
    if not hasattr(app.state, "http"):
        app.state.http = httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    if not hasattr(app.state, "redis"):
        app.state.redis = None
        if settings.storage_backend.lower() == "redis":
            try:
                if Redis is None:
                    raise RedisError("redis package is not installed")
                app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
            except RedisError as exc:
                logger.warning("Failed to initialize Redis client; using memory fallback: %s", exc)

    if not hasattr(app.state, "storage"):
        app.state.storage = create_storage_backend(redis_client=app.state.redis)

    if not hasattr(app.state, "routes"):
        app.state.routes = load_routes()


def _storage_health(app: FastAPI) -> dict[str, object]:
    configured = settings.storage_backend.lower()
    storage = getattr(app.state, "storage", None)
    redis_client = getattr(app.state, "redis", None)

    fallback_active = False
    fallback_reason: str | None = None
    effective_backend = configured

    if configured == "redis" and redis_client is None:
        fallback_active = True
        fallback_reason = "redis_client_unavailable_at_startup"
        effective_backend = "memory"

    if isinstance(storage, FallbackStorage):
        snapshot = storage.fallback_state()
        if snapshot.get("active"):
            fallback_active = True
            fallback_reason = str(snapshot.get("reason") or "runtime_redis_error")
            effective_backend = "memory_fallback"
        elif configured == "redis":
            effective_backend = "redis"

    return {
        "configured_backend": configured,
        "effective_backend": effective_backend,
        "fallback_active": fallback_active,
        "fallback_reason": fallback_reason,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown resources for the FastAPI app."""
    _initialize_app_state(app)

    auth_mode, auth_warning = describe_admin_auth_mode()
    logger.info("admin_auth_mode mode=%s", auth_mode)
    logger.info(
        "startup_summary auth_mode=%s storage_backend=%s rate_limit_backend=%s "
        "routes_configured=%s circuit_breaker_threshold=%s retries=%s",
        auth_mode,
        settings.storage_backend,
        settings.rate_limit_backend,
        bool((settings.routes_yaml or "").strip()),
        settings.circuit_breaker_threshold,
        settings.telegram_retries,
    )
    if auth_warning:
        logger.warning("admin_auth_mode_warning %s", auth_warning)

    try:
        yield
    finally:
        if getattr(app.state, "redis", None) is not None:
            if hasattr(app.state.redis, "aclose"):
                await app.state.redis.aclose()
            else:
                await app.state.redis.close()
        if getattr(app.state, "http", None) is not None:
            await app.state.http.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Webhook-to-Telegram Bridge",
        version="1.3.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(
        RateLimitMiddleware,
        backend=create_rate_limit_backend(),
        ip_limit_per_minute=settings.rate_limit_ip_per_minute,
        token_limit_per_minute=settings.rate_limit_token_per_minute,
        admin_limit_per_minute=settings.rate_limit_admin_per_minute,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(webhooks_router)
    app.include_router(sandbox_router)
    app.include_router(replay_router)
    app.include_router(ws_router)

    # Conditionally include GitHub App router
    if settings.github_app_id and settings.github_app_private_key:
        from app.api.github_app import router as github_app_router

        app.include_router(github_app_router)

    @app.exception_handler(WebhookError)
    async def webhook_error_handler(request: Request, exc: WebhookError) -> JSONResponse:
        return _error_response(request, exc.status_code, exc.error_code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("request_validation_failed errors=%s", exc.errors())
        return _error_response(request, 422, "validation_error", "Request validation failed")

    @app.get("/metrics", tags=["monitoring"])
    async def metrics() -> PlainTextResponse:
        """Prometheus metrics endpoint."""
        return PlainTextResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Basic health check."""
        return {"status": "ok"}

    @app.get("/health/deep", tags=["health"])
    async def health_deep() -> JSONResponse:
        """Deep health check - verifies Telegram API connectivity."""
        from telegram import Bot
        from telegram.error import TelegramError

        try:
            bot = Bot(token=settings.telegram_bot_token)
            me = await bot.get_me()
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "telegram": {
                        "connected": True,
                        "bot_username": me.username,
                    },
                    "circuit_breaker": {
                        "state": telegram_circuit.state.value,
                    },
                    "storage": _storage_health(app),
                    "destinations": destination_health_snapshot(),
                },
            )
        except TelegramError as exc:
            logger.warning("Deep health check failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "telegram": {"connected": False, "error": str(exc)},
                    "circuit_breaker": {
                        "state": telegram_circuit.state.value,
                    },
                    "storage": _storage_health(app),
                    "destinations": destination_health_snapshot(),
                },
            )

    return app


app = create_app()
