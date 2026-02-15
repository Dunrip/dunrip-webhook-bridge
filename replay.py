from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request

from config import settings
from exceptions import ValidationError
from formatters import get_formatter
from observability import audit_log, fingerprint_api_key
from security import get_client_ip, is_admin_ip_allowed, require_admin_scope
from storage import Storage
from tg_client import TelegramSendError, format_generic, send_message

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


async def _replay_delivery(record: dict[str, Any], storage: Storage, *, override: bool = False) -> str:
    now = time.time()
    replay_attempts = int(record.get("replay_attempts") or 0)
    last_replay_at = record.get("last_replay_at")
    if not override and replay_attempts >= settings.max_replay_attempts:
        await storage.update_failed_delivery(record["id"], {"status": "dead_letter", "last_replay_status": "max_attempts_exceeded", "last_replay_at": now})
        raise ValidationError("Replay attempts exceeded maximum; delivery moved to dead-letter queue", error_code="replay_max_attempts_exceeded", status_code=409)
    if not override and last_replay_at and now - float(last_replay_at) < settings.replay_cooldown_seconds:
        raise ValidationError("Replay cooldown active for this delivery", error_code="replay_cooldown_active", status_code=429)

    source, event_type, payload = record["source"], record["event_type"], record["payload"]
    await storage.update_failed_delivery(record["id"], {"replay_attempts": replay_attempts + 1, "last_replay_at": now, "last_replay_status": "in_progress"})

    if source == "generic":
        message = format_generic(payload.get("title", ""), payload.get("body", ""), payload.get("url"))
    else:
        formatter = get_formatter(event_type)
        if not formatter:
            await storage.update_failed_delivery(record["id"], {"last_replay_status": "failed"})
            return "failed"
        message = formatter(payload)

    try:
        await send_message(message)
        await storage.update_failed_delivery(record["id"], {"status": "delivered", "last_replay_status": "delivered"})
        return "delivered"
    except TelegramSendError:
        updated = await storage.get_failed_delivery(record["id"])
        attempts = int((updated or {}).get("replay_attempts") or (replay_attempts + 1))
        new_status = "dead_letter" if attempts >= settings.max_replay_attempts else "failed"
        await storage.update_failed_delivery(record["id"], {"status": new_status, "last_replay_status": "failed"})
        return new_status


@router.get("/deliveries")
async def list_deliveries(request: Request, source: str | None = Query(default=None), status: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), _auth: str = Depends(require_admin_scope("read")), storage: Storage = Depends(_get_storage)) -> dict[str, Any]:
    deliveries, total = await storage.list_failed_deliveries(source=source, status=status, limit=limit, offset=offset)
    audit_log(logger, action="GET /deliveries", request_id=getattr(request.state, "request_id", "-"), client_ip=get_client_ip(request), auth_result="allow", status="ok", actor_key_id=_actor_key_id_from_request(request))
    return {"deliveries": deliveries, "total": total}


@router.post("/deliveries/{delivery_id}/replay")
async def replay_delivery(delivery_id: str, request: Request, override: bool = Query(default=False), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), _auth: str = Depends(require_admin_scope("replay")), storage: Storage = Depends(_get_storage)) -> dict[str, str]:
    if idempotency_key and await storage.is_duplicate_replay_operation(f"single:{delivery_id}:{idempotency_key}", settings.replay_cooldown_seconds):
        raise ValidationError("Duplicate replay request blocked by idempotency key", error_code="replay_duplicate_request", status_code=409)
    record = await storage.get_failed_delivery(delivery_id)
    if not record:
        raise ValidationError("Delivery not found", error_code="delivery_not_found", status_code=404)
    new_status = await _replay_delivery(record, storage, override=override)
    audit_log(logger, action="POST /deliveries/{id}/replay", request_id=getattr(request.state, "request_id", "-"), client_ip=get_client_ip(request), auth_result="allow", status=new_status, actor_key_id=_actor_key_id_from_request(request), delivery_id=delivery_id)
    return {"status": new_status, "delivery_id": delivery_id}


@router.post("/deliveries/replay-all")
async def replay_all(request: Request, override: bool = Query(default=False), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), _auth: str = Depends(require_admin_scope("replay")), storage: Storage = Depends(_get_storage)) -> dict[str, int]:
    if idempotency_key and await storage.is_duplicate_replay_operation(f"all:{idempotency_key}", settings.replay_cooldown_seconds):
        raise ValidationError("Duplicate replay-all request blocked by idempotency key", error_code="replay_duplicate_request", status_code=409)
    failed, _ = await storage.list_failed_deliveries(status="failed", limit=1000, offset=0)
    attempted = succeeded = failed_count = 0
    for record in failed:
        attempted += 1
        try:
            new_status = await _replay_delivery(record, storage, override=override)
        except ValidationError:
            new_status = "failed"
        if new_status == "delivered":
            succeeded += 1
        else:
            failed_count += 1
    audit_log(logger, action="POST /deliveries/replay-all", request_id=getattr(request.state, "request_id", "-"), client_ip=get_client_ip(request), auth_result="allow", status="ok", actor_key_id=_actor_key_id_from_request(request))
    return {"attempted": attempted, "succeeded": succeeded, "failed": failed_count}
