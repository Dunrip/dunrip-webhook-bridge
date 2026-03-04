from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.security import get_client_ip, is_admin_ip_allowed, require_admin_scope
from app.infra.storage import Storage
from app.observability.observability import audit_log, fingerprint_api_key
from app.services.formatters import get_formatter
from app.services.reliability import payload_hash
from app.services.routing import Route, route_event
from app.services.tg_client import TelegramSendError, format_generic, send_message

logger = logging.getLogger(__name__)


async def verify_admin_ip_allowlist(request: Request) -> str:
    client_ip = get_client_ip(request)
    if is_admin_ip_allowed(client_ip):
        return "ok"

    actor = _actor_key_id_from_request(request)
    request_id = getattr(request.state, "request_id", "-")
    action = f"{request.method} {request.url.path}"
    audit_log(
        logger,
        action=action,
        request_id=request_id,
        client_ip=client_ip,
        auth_result="deny",
        status="admin_allowlist_denied",
        actor_key_id=actor,
        reason="admin_allowlist_denied",
    )
    raise ValidationError(
        "Client IP is not allowed for admin endpoints",
        error_code="ADMIN_IP_NOT_ALLOWED",
        status_code=403,
    )


router = APIRouter(tags=["replay"], dependencies=[Depends(verify_admin_ip_allowlist)])


def _get_storage(request: Request) -> Storage:
    return request.app.state.storage


def _actor_key_id_from_request(request: Request) -> str:
    key = request.headers.get("x-api-key")
    if not key and request.headers.get("authorization", "").lower().startswith("bearer "):
        key = request.headers.get("authorization", "")[7:].strip()
    return fingerprint_api_key(key)


async def _replay_delivery(
    record: dict[str, Any],
    storage: Storage,
    *,
    routes: list[Route] | None = None,
    http_client: httpx.AsyncClient | None = None,
    override: bool = False,
) -> str:
    now = time.time()
    replay_attempts = int(record.get("replay_attempts") or 0)
    last_replay_at = record.get("last_replay_at")
    if not override and replay_attempts >= settings.max_replay_attempts:
        await storage.update_failed_delivery(
            record["id"],
            {"status": "dead_letter", "last_replay_status": "max_attempts_exceeded", "last_replay_at": now},
        )
        raise ValidationError(
            "Replay attempts exceeded maximum; delivery moved to dead-letter queue",
            error_code="replay_max_attempts_exceeded",
            status_code=409,
        )
    if not override and last_replay_at and now - float(last_replay_at) < settings.replay_cooldown_seconds:
        raise ValidationError(
            "Replay cooldown active for this delivery", error_code="replay_cooldown_active", status_code=429
        )

    source, event_type, payload = record["source"], record["event_type"], record["payload"]
    inbound_delivery_id = record.get("delivery_id") or record["id"]
    record_hash = payload_hash(payload)
    await storage.update_failed_delivery(
        record["id"],
        {"replay_attempts": replay_attempts + 1, "last_replay_at": now, "last_replay_status": "in_progress"},
    )

    if source == "generic":
        message = format_generic(payload.get("title", ""), payload.get("body", ""), payload.get("url"))
    else:
        formatter = get_formatter(event_type)
        if not formatter:
            await storage.update_failed_delivery(record["id"], {"last_replay_status": "failed"})
            await storage.upsert_delivery_ledger(
                source, inbound_delivery_id, record_hash, "failed", "formatter_not_found"
            )
            return "failed"
        message = formatter(payload)

    if routes:
        results = await route_event(routes, message, event_type, payload, http_client=http_client)
        any_sent = any(result.get("status") == "sent" for result in results)
        any_failed = any(result.get("status") == "failed" for result in results)

        if any_sent:
            await storage.update_failed_delivery(
                record["id"],
                {
                    "status": "delivered",
                    "last_replay_status": "delivered",
                    "last_replay_routing": results,
                },
            )
            await storage.upsert_delivery_ledger(source, inbound_delivery_id, record_hash, "delivered")
            return "delivered"

        updated = await storage.get_failed_delivery(record["id"])
        attempts = int((updated or {}).get("replay_attempts") or (replay_attempts + 1))
        new_status = "dead_letter" if attempts >= settings.max_replay_attempts else "failed"
        reason = "replay_routed_delivery_failed" if any_failed else "replay_no_matching_route"
        await storage.update_failed_delivery(
            record["id"],
            {
                "status": new_status,
                "last_replay_status": "failed",
                "last_replay_routing": results,
            },
        )
        await storage.upsert_delivery_ledger(source, inbound_delivery_id, record_hash, "failed", reason)
        return new_status

    try:
        await send_message(message)
        await storage.update_failed_delivery(record["id"], {"status": "delivered", "last_replay_status": "delivered"})
        await storage.upsert_delivery_ledger(source, inbound_delivery_id, record_hash, "delivered")
        return "delivered"
    except TelegramSendError:
        updated = await storage.get_failed_delivery(record["id"])
        attempts = int((updated or {}).get("replay_attempts") or (replay_attempts + 1))
        new_status = "dead_letter" if attempts >= settings.max_replay_attempts else "failed"
        await storage.update_failed_delivery(record["id"], {"status": new_status, "last_replay_status": "failed"})
        await storage.upsert_delivery_ledger(
            source, inbound_delivery_id, record_hash, "failed", "replay_delivery_failed"
        )
        return new_status


@router.get("/deliveries")
async def list_deliveries(
    request: Request,
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: str = Depends(require_admin_scope("read")),
    storage: Storage = Depends(_get_storage),
) -> dict[str, Any]:
    deliveries, total = await storage.list_failed_deliveries(source=source, status=status, limit=limit, offset=offset)
    audit_log(
        logger,
        action="GET /deliveries",
        request_id=getattr(request.state, "request_id", "-"),
        client_ip=get_client_ip(request),
        auth_result="allow",
        status="ok",
        actor_key_id=_actor_key_id_from_request(request),
    )
    return {"deliveries": deliveries, "total": total}


@router.get("/deliveries/recent")
async def list_recent_deliveries(
    request: Request,
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _auth: str = Depends(require_admin_scope("read")),
    storage: Storage = Depends(_get_storage),
) -> dict[str, Any]:
    records = await storage.list_recent_delivery_ledger(provider=source, status=status, limit=limit)
    audit_log(
        logger,
        action="GET /deliveries/recent",
        request_id=getattr(request.state, "request_id", "-"),
        client_ip=get_client_ip(request),
        auth_result="allow",
        status="ok",
        actor_key_id=_actor_key_id_from_request(request),
    )
    return {"deliveries": records, "total": len(records)}


@router.post("/deliveries/{delivery_id}/replay")
async def replay_delivery(
    delivery_id: str,
    request: Request,
    override: bool = Query(default=False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _auth: str = Depends(require_admin_scope("replay")),
    storage: Storage = Depends(_get_storage),
) -> dict[str, str]:
    if idempotency_key and await storage.is_duplicate_replay_operation(
        f"single:{delivery_id}:{idempotency_key}", settings.replay_cooldown_seconds
    ):
        raise ValidationError(
            "Duplicate replay request blocked by idempotency key",
            error_code="replay_duplicate_request",
            status_code=409,
        )
    record = await storage.get_failed_delivery(delivery_id)
    if not record:
        raise ValidationError("Delivery not found", error_code="delivery_not_found", status_code=404)
    provider = record.get("source", "generic")
    headers = record.get("headers") or {}
    inbound_delivery_id = record.get("delivery_id") or headers.get("x-request-id") or record["id"]
    ledger = await storage.get_delivery_ledger(provider, inbound_delivery_id)
    if ledger and ledger.get("status") == "delivered" and not override:
        raise ValidationError(
            "Replay blocked: delivery already marked delivered in ledger",
            error_code="replay_already_delivered",
            status_code=409,
        )
    routes = getattr(request.app.state, "routes", None)
    http_client = getattr(request.app.state, "http", None)
    new_status = await _replay_delivery(record, storage, routes=routes, http_client=http_client, override=override)
    audit_log(
        logger,
        action="POST /deliveries/{id}/replay",
        request_id=getattr(request.state, "request_id", "-"),
        client_ip=get_client_ip(request),
        auth_result="allow",
        status=new_status,
        actor_key_id=_actor_key_id_from_request(request),
        delivery_id=delivery_id,
    )
    return {"status": new_status, "delivery_id": delivery_id}


async def _replay_all_background(
    records: list[dict[str, Any]],
    storage: Storage,
    *,
    routes: list[Route] | None = None,
    http_client: httpx.AsyncClient | None = None,
    override: bool = False,
) -> None:
    """Process replay-all deliveries in the background with bounded concurrency."""
    sem = asyncio.Semaphore(10)

    async def _replay_one(record: dict[str, Any]) -> None:
        async with sem:
            try:
                await _replay_delivery(record, storage, routes=routes, http_client=http_client, override=override)
            except (ValidationError, Exception):
                logger.warning("Background replay failed for record=%s", record.get("id"))

    await asyncio.gather(*[_replay_one(r) for r in records])


@router.post("/deliveries/replay-all")
async def replay_all(
    request: Request,
    background_tasks: BackgroundTasks,
    override: bool = Query(default=False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _auth: str = Depends(require_admin_scope("replay")),
    storage: Storage = Depends(_get_storage),
) -> dict[str, Any]:
    if idempotency_key and await storage.is_duplicate_replay_operation(
        f"all:{idempotency_key}", settings.replay_cooldown_seconds
    ):
        raise ValidationError(
            "Duplicate replay-all request blocked by idempotency key",
            error_code="replay_duplicate_request",
            status_code=409,
        )
    failed, _ = await storage.list_failed_deliveries(status="failed", limit=1000, offset=0)
    queued = len(failed)

    if queued > 0:
        routes = getattr(request.app.state, "routes", None)
        http_client = getattr(request.app.state, "http", None)
        background_tasks.add_task(
            _replay_all_background,
            failed,
            storage,
            routes=routes,
            http_client=http_client,
            override=override,
        )

    audit_log(
        logger,
        action="POST /deliveries/replay-all",
        request_id=getattr(request.state, "request_id", "-"),
        client_ip=get_client_ip(request),
        auth_result="allow",
        status="accepted",
        actor_key_id=_actor_key_id_from_request(request),
    )
    return {"status": "accepted", "queued": queued}
