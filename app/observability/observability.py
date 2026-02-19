from __future__ import annotations

import contextvars
import hashlib
import logging
from uuid import uuid4

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def fingerprint_api_key(api_key: str | None) -> str:
    """Return a deterministic non-reversible API-key identifier for logs."""
    if not api_key:
        return "api-key:anonymous"
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
    return f"key_{digest}"


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_ctx.get()
        return True


def new_request_id() -> str:
    return str(uuid4())


def get_request_id() -> str:
    return request_id_ctx.get()


def audit_log(
    logger: logging.Logger,
    *,
    action: str,
    request_id: str,
    client_ip: str,
    auth_result: str,
    status: str,
    actor_key_id: str,
    reason: str | None = None,
    delivery_id: str | None = None,
) -> None:
    """Emit structured audit event for sensitive admin actions."""
    logger.info(
        "admin_audit action=%s request_id=%s client_ip=%s auth_result=%s "
        "delivery_id=%s status=%s actor_key_id=%s reason=%s",
        action,
        request_id,
        client_ip,
        auth_result,
        delivery_id or "-",
        status,
        actor_key_id,
        reason or "-",
    )
