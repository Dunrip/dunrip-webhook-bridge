"""FastAPI application entrypoint for the webhook bridge service.

This module wires app lifecycle, middleware, observability, routing, and
webhook endpoints for GitHub and generic payload forwarding.
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from json import JSONDecodeError
import httpx

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

from app.infra.circuit_breaker import telegram_circuit
from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.exceptions import CircuitBreakerError, ValidationError, WebhookError
from app.services.formatters import get_formatter
from app.infra.middleware import RequestContextMiddleware, RateLimitMiddleware, create_rate_limit_backend
from app.observability.observability import RequestContextFilter
from app.models.models import GenericWebhookPayload
from app.api.replay import router as replay_router
from app.services.routing import load_routes, route_event
from app.api.sandbox import router as sandbox_router
from app.core.security import describe_admin_auth_mode, verify_generic_token, verify_github_signature
from app.infra.storage import FallbackStorage, Redis, RedisError, Storage, create_storage_backend
from app.services.reliability import payload_hash
from app.services.tg_client import TelegramSendError, format_generic, send_message
from app.api.websocket import broadcaster, router as ws_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestContextFilter())
logger = logging.getLogger(__name__)

# Prometheus metrics with guards to avoid duplicate registration in tests
def _get_or_create_counter(name: str, description: str, labels: list[str]) -> Counter:
    from prometheus_client import REGISTRY
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Counter(name, description, labels)


def _get_or_create_histogram(name: str, description: str, labels: list[str], buckets: list[float] | None = None) -> Histogram:
    from prometheus_client import REGISTRY
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    if buckets:
        return Histogram(name, description, labels, buckets=buckets)
    return Histogram(name, description, labels)


WEBHOOK_REQUESTS = _get_or_create_counter(
    "webhook_requests_total",
    "Total webhook requests",
    ["source", "event_type", "status"]
)

WEBHOOK_LATENCY = _get_or_create_histogram(
    "webhook_request_duration_seconds",
    "Webhook request latency",
    ["source", "event_type"],
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0]
)

ENQUEUE_LATENCY = _get_or_create_histogram(
    "webhook_enqueue_duration_seconds",
    "Time spent validating and enqueueing webhook payloads",
    ["source"],
)

PROCESSING_LATENCY = _get_or_create_histogram(
    "webhook_processing_duration_seconds",
    "Time spent processing webhook deliveries",
    ["source", "event_type"],
)

RETRY_TOTAL = _get_or_create_counter(
    "webhook_retries_total",
    "Retry attempts by classification",
    ["classification"],
)

DLQ_GROWTH_TOTAL = _get_or_create_counter(
    "webhook_dlq_growth_total",
    "Dead-letter growth by reason",
    ["reason"],
)

TELEGRAM_MESSAGES = _get_or_create_counter(
    "telegram_messages_total",
    "Total Telegram messages sent",
    ["status"]
)

CIRCUIT_BREAKER_STATE = _get_or_create_counter(
    "circuit_breaker_state_changes_total",
    "Circuit breaker state changes",
    ["from_state", "to_state"]
)


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


def _with_request_id_footer(message: str, request_id: str) -> str:
    return f"{message}\n\n`request_id: {request_id}`"


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

def _get_storage(request: Request) -> Storage:
    _initialize_app_state(request.app)
    return request.app.state.storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown resources for the FastAPI app."""
    _initialize_app_state(app)

    auth_mode, auth_warning = describe_admin_auth_mode()
    logger.info("admin_auth_mode mode=%s", auth_mode)
    logger.info(
        "startup_summary auth_mode=%s storage_backend=%s rate_limit_backend=%s routes_configured=%s circuit_breaker_threshold=%s retries=%s",
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
        return PlainTextResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )

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
                },
            )

    @app.post("/webhook/github", tags=["webhooks"])
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default="ping"),
        x_github_delivery: str | None = Header(default=None),
        storage: Storage = Depends(_get_storage),
    ) -> dict[str, str]:
        """Receive GitHub webhooks and forward to Telegram."""
        start_time = time.time()
        logger.info(
            "webhook_received source=github event_type=%s delivery_id=%s",
            x_github_event,
            x_github_delivery,
        )

        try:
            body = await verify_github_signature(request)
        except WebhookError:
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="auth_error"
            ).inc()
            raise

        request_start = time.time()
        body_hash = payload_hash(body)
        if x_github_delivery:
            existing = await storage.get_delivery_ledger("github", x_github_delivery)
            if existing and existing.get("payload_hash") != body_hash:
                WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="replay_rejected").inc()
                return _error_response(request, 409, "replay_mismatch", "Delivery id already seen with different payload hash")
            await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "received")

        # Idempotency check (after signature verification to prevent poisoning)
        if await storage.is_duplicate_delivery(x_github_delivery):
            logger.warning("webhook_duplicate source=github event_type=%s delivery_id=%s", x_github_event, x_github_delivery)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="duplicate"
            ).inc()
            if x_github_delivery:
                await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "duplicate")
            return _error_response(
                request,
                409,
                "duplicate_delivery",
                f"Duplicate delivery: {x_github_delivery or 'unknown'}",
            )

        ENQUEUE_LATENCY.labels(source="github").observe(time.time() - request_start)

        if x_github_event == "ping":
            WEBHOOK_REQUESTS.labels(
                source="github", event_type="ping", status="success"
            ).inc()
            return {"status": "pong"}

        try:
            payload = json.loads(body)
        except JSONDecodeError as exc:
            logger.warning("Malformed JSON in GitHub webhook event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="malformed_json"
            ).inc()
            raise ValidationError("Malformed JSON payload", error_code="malformed_json") from exc

        formatter = get_formatter(x_github_event)
        if not formatter:
            logger.info("Ignoring unsupported GitHub event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="ignored"
            ).inc()
            return {"status": "ignored", "event": x_github_event}

        if not isinstance(payload, dict):
            logger.warning("GitHub payload is not an object event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="invalid_payload"
            ).inc()
            raise ValidationError("Payload must be a JSON object")

        message = formatter(payload)

        routes = request.app.state.routes
        if routes:
            # Multi-destination routing
            results = await route_event(
                routes,
                message,
                x_github_event,
                payload,
                http_client=request.app.state.http,
            )
            any_sent = any(r["status"] == "sent" for r in results)
            any_failed = any(r["status"] == "failed" for r in results)

            if any_sent:
                TELEGRAM_MESSAGES.labels(status="success").inc()
                if x_github_delivery:
                    await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "delivered")
            if any_failed:
                TELEGRAM_MESSAGES.labels(status="failed").inc()
                if x_github_delivery:
                    await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "failed", "partial_delivery_failure")
                DLQ_GROWTH_TOTAL.labels(reason="partial_delivery_failure").inc()
                await storage.store_failed_delivery(
                    source="github",
                    event_type=x_github_event,
                    payload=payload,
                    headers={
                        "x-github-event": x_github_event,
                        "x-github-delivery": x_github_delivery or "",
                    },
                    error="Partial delivery failure",
                    delivery_id=x_github_delivery,
                )

            status = "success" if any_sent else ("delivery_failed" if any_failed else "ignored")
            duration = time.time() - start_time
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status=status
            ).inc()
            WEBHOOK_LATENCY.labels(
                source="github", event_type=x_github_event
            ).observe(duration)
            PROCESSING_LATENCY.labels(source="github", event_type=x_github_event).observe(duration)
            logger.info(
                "webhook_delivery source=github event_type=%s delivery_id=%s status=%s duration_ms=%.2f routed=%d",
                x_github_event,
                x_github_delivery,
                status,
                duration * 1000,
                len(results),
            )

            # Broadcast to WebSocket clients
            await broadcaster.broadcast({
                "source": "github",
                "event_type": x_github_event,
                "status": status,
                "payload": payload,
                "routing_results": results,
            })

            if not any_sent and any_failed:
                raise CircuitBreakerError("Failed to deliver message", error_code="delivery_failed", status_code=502)

            logger.info("GitHub event routed event=%s results=%s", x_github_event, results)
            return {"status": "sent", "event": x_github_event, "routing": results}

        # Default: send to Telegram only (no routing configured)
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
            if x_github_delivery:
                await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "delivered")
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="success"
            ).inc()
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for event=%s", x_github_event)
            await storage.store_failed_delivery(
                source="github",
                event_type=x_github_event,
                payload=payload,
                headers={
                    "x-github-event": x_github_event,
                    "x-github-delivery": x_github_delivery or "",
                },
                error=str(exc),
                delivery_id=x_github_delivery,
            )
            DLQ_GROWTH_TOTAL.labels(reason="delivery_failed").inc()
            RETRY_TOTAL.labels(classification="network").inc()
            if x_github_delivery:
                await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "failed", "delivery_failed")
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="delivery_failed"
            ).inc()
            raise CircuitBreakerError("Failed to deliver message", error_code="delivery_failed", status_code=502) from exc
        finally:
            duration = time.time() - start_time
            WEBHOOK_LATENCY.labels(
                source="github", event_type=x_github_event
            ).observe(duration)
            PROCESSING_LATENCY.labels(source="github", event_type=x_github_event).observe(duration)

        # Broadcast to WebSocket clients
        await broadcaster.broadcast({
            "source": "github",
            "event_type": x_github_event,
            "status": "success",
            "payload": payload,
        })

        logger.info("GitHub event delivered event=%s", x_github_event)
        return {"status": "sent", "event": x_github_event}

    @app.post("/webhook/generic", tags=["webhooks"])
    async def generic_webhook(
        request: Request,
        payload: GenericWebhookPayload,
        _token: str = Depends(verify_generic_token),
        storage: Storage = Depends(_get_storage),
    ) -> dict[str, str]:
        """Receive generic webhooks and forward to Telegram."""
        start_time = time.time()
        request_start = time.time()
        logger.info("webhook_received source=generic event_type=generic title=%s", payload.title)
        message = format_generic(payload.title, payload.body, payload.url)
        payload_dict = payload.model_dump()
        generic_delivery_id = _request_id(request)
        generic_hash = payload_hash(payload_dict)
        await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "received")
        ENQUEUE_LATENCY.labels(source="generic").observe(time.time() - request_start)

        routes = request.app.state.routes
        if routes:
            results = await route_event(
                routes,
                message,
                "generic",
                payload_dict,
                http_client=request.app.state.http,
            )
            any_sent = any(r["status"] == "sent" for r in results)
            any_failed = any(r["status"] == "failed" for r in results)

            if any_sent:
                TELEGRAM_MESSAGES.labels(status="success").inc()
                await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "delivered")
            if any_failed:
                TELEGRAM_MESSAGES.labels(status="failed").inc()
                await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "failed", "partial_delivery_failure")
                DLQ_GROWTH_TOTAL.labels(reason="partial_delivery_failure").inc()
                await storage.store_failed_delivery(
                    source="generic", event_type="generic",
                    payload=payload_dict, headers={"x-request-id": generic_delivery_id},
                    error="Partial delivery failure",
                    delivery_id=generic_delivery_id,
                )

            status = "success" if any_sent else ("delivery_failed" if any_failed else "ignored")
            duration = time.time() - start_time
            WEBHOOK_REQUESTS.labels(source="generic", event_type="generic", status=status).inc()
            WEBHOOK_LATENCY.labels(source="generic", event_type="generic").observe(duration)
            PROCESSING_LATENCY.labels(source="generic", event_type="generic").observe(duration)
            logger.info(
                "webhook_delivery source=generic event_type=generic status=%s duration_ms=%.2f routed=%d",
                status,
                duration * 1000,
                len(results),
            )

            await broadcaster.broadcast({
                "source": "generic", "event_type": "generic",
                "status": status, "payload": payload_dict, "routing_results": results,
            })

            if not any_sent and any_failed:
                raise CircuitBreakerError("Failed to deliver message", error_code="delivery_failed", status_code=502)

            return {"status": "sent", "routing": results}

        # Default: Telegram only
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
            await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "delivered")
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="success"
            ).inc()
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for generic webhook")
            await storage.store_failed_delivery(
                source="generic",
                event_type="generic",
                payload=payload_dict,
                headers={"x-request-id": generic_delivery_id},
                error=str(exc),
                delivery_id=generic_delivery_id,
            )
            DLQ_GROWTH_TOTAL.labels(reason="delivery_failed").inc()
            RETRY_TOTAL.labels(classification="network").inc()
            await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "failed", "delivery_failed")
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="delivery_failed"
            ).inc()
            raise CircuitBreakerError("Failed to deliver message", error_code="delivery_failed", status_code=502) from exc
        finally:
            duration = time.time() - start_time
            WEBHOOK_LATENCY.labels(
                source="generic", event_type="generic"
            ).observe(duration)
            PROCESSING_LATENCY.labels(source="generic", event_type="generic").observe(duration)

        await broadcaster.broadcast({
            "source": "generic", "event_type": "generic",
            "status": "success", "payload": payload_dict,
        })

        logger.info("Generic webhook delivered")
        return {"status": "sent"}

    return app


app = create_app()
