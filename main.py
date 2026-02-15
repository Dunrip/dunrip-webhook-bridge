import json
import logging
import time
from contextlib import asynccontextmanager
from json import JSONDecodeError
from typing import Any

import httpx

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from circuit_breaker import telegram_circuit
from config import settings
from formatters import get_formatter
from middleware import RateLimitMiddleware, create_rate_limit_backend
from models import GenericWebhookPayload
from replay import router as replay_router
from routing import load_routes, route_event
from sandbox import router as sandbox_router
from security import verify_generic_token, verify_github_signature
from storage import Redis, RedisError, Storage, create_storage_backend
from tg_client import TelegramSendError, format_generic, send_message
from websocket import broadcaster, router as ws_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Prometheus metrics
WEBHOOK_REQUESTS = Counter(
    "webhook_requests_total",
    "Total webhook requests",
    ["source", "event_type", "status"]
)

WEBHOOK_LATENCY = Histogram(
    "webhook_request_duration_seconds",
    "Webhook request latency",
    ["source", "event_type"],
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0]
)

TELEGRAM_MESSAGES = Counter(
    "telegram_messages_total",
    "Total Telegram messages sent",
    ["status"]
)

CIRCUIT_BREAKER_STATE = Counter(
    "circuit_breaker_state_changes_total",
    "Circuit breaker state changes",
    ["from_state", "to_state"]
)

def _initialize_app_state(app: FastAPI) -> None:
    if not hasattr(app.state, "http"):
        app.state.http = httpx.AsyncClient(timeout=10)

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


def _get_storage(request: Request) -> Storage:
    _initialize_app_state(request.app)
    return request.app.state.storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    _initialize_app_state(app)

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
    )
    app.include_router(sandbox_router)
    app.include_router(replay_router)
    app.include_router(ws_router)

    # Conditionally include GitHub App router
    if settings.github_app_id and settings.github_app_private_key:
        from github_app import router as github_app_router
        app.include_router(github_app_router)

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
            "Received GitHub webhook event=%s delivery=%s",
            x_github_event,
            x_github_delivery,
        )

        try:
            body = await verify_github_signature(request)
        except HTTPException as exc:
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="auth_error"
            ).inc()
            raise

        # Idempotency check (after signature verification to prevent poisoning)
        if await storage.is_duplicate_delivery(x_github_delivery):
            logger.info("Duplicate delivery %s ignored", x_github_delivery)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="duplicate"
            ).inc()
            return JSONResponse(
                status_code=409,
                content={"status": "duplicate", "delivery_id": x_github_delivery or "unknown"},
            )

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
            raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

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
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

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
            if any_failed:
                TELEGRAM_MESSAGES.labels(status="failed").inc()
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
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status=status
            ).inc()
            WEBHOOK_LATENCY.labels(
                source="github", event_type=x_github_event
            ).observe(time.time() - start_time)

            # Broadcast to WebSocket clients
            await broadcaster.broadcast({
                "source": "github",
                "event_type": x_github_event,
                "status": status,
                "payload": payload,
                "routing_results": results,
            })

            if not any_sent and any_failed:
                raise HTTPException(status_code=502, detail="Failed to deliver message")

            logger.info("GitHub event routed event=%s results=%s", x_github_event, results)
            return {"status": "sent", "event": x_github_event, "routing": results}

        # Default: send to Telegram only (no routing configured)
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
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
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="delivery_failed"
            ).inc()
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc
        finally:
            WEBHOOK_LATENCY.labels(
                source="github", event_type=x_github_event
            ).observe(time.time() - start_time)

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
        logger.info("Received generic webhook title=%s", payload.title)
        message = format_generic(payload.title, payload.body, payload.url)
        payload_dict = payload.model_dump()

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
            if any_failed:
                TELEGRAM_MESSAGES.labels(status="failed").inc()
                await storage.store_failed_delivery(
                    source="generic", event_type="generic",
                    payload=payload_dict, headers={},
                    error="Partial delivery failure",
                )

            status = "success" if any_sent else ("delivery_failed" if any_failed else "ignored")
            WEBHOOK_REQUESTS.labels(source="generic", event_type="generic", status=status).inc()
            WEBHOOK_LATENCY.labels(source="generic", event_type="generic").observe(time.time() - start_time)

            await broadcaster.broadcast({
                "source": "generic", "event_type": "generic",
                "status": status, "payload": payload_dict, "routing_results": results,
            })

            if not any_sent and any_failed:
                raise HTTPException(status_code=502, detail="Failed to deliver message")

            return {"status": "sent", "routing": results}

        # Default: Telegram only
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="success"
            ).inc()
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for generic webhook")
            await storage.store_failed_delivery(
                source="generic",
                event_type="generic",
                payload=payload_dict,
                headers={},
                error=str(exc),
            )
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="delivery_failed"
            ).inc()
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc
        finally:
            WEBHOOK_LATENCY.labels(
                source="generic", event_type="generic"
            ).observe(time.time() - start_time)

        await broadcaster.broadcast({
            "source": "generic", "event_type": "generic",
            "status": "success", "payload": payload_dict,
        })

        logger.info("Generic webhook delivered")
        return {"status": "sent"}

    return app


app = create_app()
