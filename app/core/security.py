from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial

import anyio
from fastapi import Header, Request, WebSocket

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.observability.observability import audit_log, fingerprint_api_key

logger = logging.getLogger(__name__)
_VALID_SCOPES = {"read", "replay", "admin"}


@dataclass
class AdminAuthResult:
    ok: bool
    reason: str
    scope: str | None
    actor_key_id: str
    used_previous_key: bool = False


def _parse_networks(
    raw: str,
    setting_name: str,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated list of IP/CIDR entries into network objects."""
    value = (raw or "").strip()
    if not value:
        return []

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid %s entry: %s", setting_name, candidate)
    return networks


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return _parse_networks(settings.trusted_proxies, "TRUSTED_PROXIES")


def _admin_allowlist_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return _parse_networks(settings.admin_ip_allowlist, "ADMIN_IP_ALLOWLIST")


def _ws_allowlist_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    ws_raw = (settings.ws_ip_allowlist or "").strip()
    if ws_raw:
        return _parse_networks(ws_raw, "WS_IP_ALLOWLIST")
    return _admin_allowlist_networks()


def _is_trusted_proxy(
    ip: str,
    trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(ip_obj in network for network in trusted_networks)


def _resolve_effective_client_ip(direct_ip: str, forwarded_for: str | None) -> str:
    trusted_networks = _trusted_proxy_networks()
    if not trusted_networks:
        return direct_ip
    if not _is_trusted_proxy(direct_ip, trusted_networks):
        return direct_ip
    if not forwarded_for:
        return direct_ip
    parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if not parts:
        return direct_ip
    candidate_ip = parts[-1]
    try:
        ipaddress.ip_address(candidate_ip)
    except ValueError:
        logger.warning("Invalid X-Forwarded-For IP from trusted proxy: %s", candidate_ip)
        return direct_ip
    return candidate_ip


def get_client_ip(request: Request) -> str:
    """Determine the effective client IP address for HTTP requests."""
    direct_ip = request.client.host if request.client else "unknown"
    return _resolve_effective_client_ip(direct_ip, request.headers.get("x-forwarded-for"))


def get_websocket_client_ip(ws: WebSocket) -> str:
    """Determine the effective client IP address for websocket connections."""
    direct_ip = ws.client.host if ws.client else "unknown"
    return _resolve_effective_client_ip(direct_ip, ws.headers.get("x-forwarded-for"))


def is_admin_ip_allowed(client_ip: str) -> bool:
    networks = _admin_allowlist_networks()
    if not networks:
        return True
    return _is_trusted_proxy(client_ip, networks)


def is_ws_ip_allowed(client_ip: str) -> bool:
    networks = _ws_allowlist_networks()
    if not networks:
        return True
    return _is_trusted_proxy(client_ip, networks)


def _compute_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_github_signature(request: Request) -> bytes:
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise AuthenticationError("Missing signature header", error_code="AUTH_MISSING_KEY")
    body = await request.body()
    if len(body) > settings.max_body_size:
        raise ValidationError("Payload too large", error_code="VALIDATION_ERROR", status_code=413)
    expected = await anyio.to_thread.run_sync(partial(_compute_signature, body, settings.github_webhook_secret))
    if not hmac.compare_digest(expected, signature_header):
        raise AuthenticationError("Invalid signature", error_code="WEBHOOK_INVALID_SIGNATURE")
    return body


def verify_generic_token(x_webhook_token: str | None = Header(default=None)) -> str:
    if x_webhook_token is None:
        raise AuthenticationError("Missing token header", error_code="AUTH_MISSING_KEY")
    if not hmac.compare_digest(x_webhook_token, settings.generic_webhook_token):
        raise AuthenticationError("Invalid token", error_code="AUTH_INVALID_KEY")
    return x_webhook_token


def _extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip() or None


def _parse_scoped_keys(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in (raw or "").split(","):
        pair = item.strip()
        if not pair or ":" not in pair:
            continue
        key, scope = pair.split(":", 1)
        key, scope = key.strip(), scope.strip().lower()
        if key and scope in _VALID_SCOPES:
            parsed[key] = scope
    return parsed


def _parse_admin_keys(raw: str) -> dict[str, str]:
    """Parse ADMIN_API_KEYS-style values.

    Supports both scoped pairs ("key:scope") and bare keys ("key"), where
    bare keys are treated as admin scope for one-key/simple setups.
    """
    parsed: dict[str, str] = {}
    for item in (raw or "").split(","):
        token = item.strip()
        if not token:
            continue
        if ":" in token:
            key, scope = token.split(":", 1)
            key, scope = key.strip(), scope.strip().lower()
            if key and scope in _VALID_SCOPES:
                parsed[key] = scope
            continue
        parsed[token] = "admin"
    return parsed


def _parse_rotation_started_at(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _scope_allows(assigned: str, required: str) -> bool:
    if assigned == "admin":
        return True
    if required == "read":
        return assigned in {"read", "replay"}
    if required == "replay":
        return assigned == "replay"
    return assigned == required


def _resolve_admin_keys() -> tuple[dict[str, str], dict[str, str]]:
    active = _parse_admin_keys(settings.admin_api_keys_active)
    previous = _parse_admin_keys(settings.admin_api_keys_previous)
    if active:
        return active, previous
    scoped = _parse_admin_keys(settings.admin_api_keys)
    if scoped:
        return scoped, {}
    if settings.admin_api_key:
        return {settings.admin_api_key: "admin"}, {}
    return {}, {}


def describe_admin_auth_mode() -> tuple[str, str | None]:
    """Return active admin auth mode and optional warning.

    Modes:
    - scoped-rotation: ADMIN_API_KEYS_ACTIVE (and optional PREVIOUS)
    - scoped: ADMIN_API_KEYS
    - legacy: ADMIN_API_KEY
    - unconfigured: no admin key present
    """
    has_legacy = bool((settings.admin_api_key or "").strip())
    has_scoped = bool((settings.admin_api_keys or "").strip())
    has_active = bool((settings.admin_api_keys_active or "").strip())
    has_previous = bool((settings.admin_api_keys_previous or "").strip())

    warning: str | None = None
    if (has_scoped or has_active or has_previous) and has_legacy:
        warning = (
            "Conflicting admin auth env vars detected: ADMIN_API_KEYS* and ADMIN_API_KEY are both set. "
            "The service will use ADMIN_API_KEYS*. Remove ADMIN_API_KEY (recommended) or clear ADMIN_API_KEYS* to use legacy mode."
        )

    if has_active:
        return "scoped-rotation", warning
    if has_scoped:
        return "scoped", warning
    if has_legacy:
        return "legacy", warning
    return "unconfigured", warning


def authenticate_admin_api_key_headers(headers: Mapping[str, str], *, required_scope: str = "admin") -> AdminAuthResult:
    provided = _extract_api_key(headers.get("authorization"), headers.get("x-api-key"))
    actor_key_id = fingerprint_api_key(provided)
    if provided is None:
        return AdminAuthResult(False, "missing", None, actor_key_id)
    active, previous = _resolve_admin_keys()
    if not active and not previous:
        return AdminAuthResult(False, "not_configured", None, actor_key_id)
    scope = active.get(provided)
    if scope:
        allowed = _scope_allows(scope, required_scope)
        return AdminAuthResult(allowed, "ok" if allowed else "expired_scope", scope, actor_key_id)
    prev_scope = previous.get(provided)
    if prev_scope:
        started_at = _parse_rotation_started_at(settings.admin_key_rotation_started_at)
        if started_at is None or (time.time() - started_at) > max(int(settings.admin_key_rotation_grace_seconds), 0):
            return AdminAuthResult(False, "expired_previous_key", prev_scope, actor_key_id, True)
        allowed = _scope_allows(prev_scope, required_scope)
        return AdminAuthResult(allowed, "ok" if allowed else "expired_scope", prev_scope, actor_key_id, True)
    return AdminAuthResult(False, "invalid", None, actor_key_id)


def validate_admin_api_key_headers(headers: Mapping[str, str]) -> bool:
    return authenticate_admin_api_key_headers(headers, required_scope="admin").ok


def require_admin_scope(required_scope: str):
    async def _dependency(request: Request) -> str:
        rid = getattr(request.state, "request_id", "-")
        ip = get_client_ip(request)
        action = f"{request.method} {request.url.path}"
        result = authenticate_admin_api_key_headers(request.headers, required_scope=required_scope)
        if result.reason == "not_configured":
            audit_log(logger, action=action, request_id=rid, client_ip=ip, auth_result="error", status="admin_key_not_configured", actor_key_id=result.actor_key_id, reason=result.reason)
            raise AuthenticationError("Admin API key not configured", error_code="admin_key_not_configured", status_code=503)
        if not result.ok:
            audit_log(logger, action=action, request_id=rid, client_ip=ip, auth_result="deny", status="auth_failed", actor_key_id=result.actor_key_id, reason=result.reason)
            if result.reason == "missing":
                raise AuthenticationError("Missing API key", error_code="missing")
            if result.reason == "expired_scope":
                raise AuthenticationError("Insufficient key scope", error_code="expired_scope", status_code=403)
            if result.reason == "expired_previous_key":
                raise AuthenticationError("Previous key expired", error_code="expired_previous_key")
            raise AuthenticationError("Invalid API key", error_code="invalid")
        if result.used_previous_key:
            logger.warning("Admin endpoint using previous key within grace window actor_key_id=%s", result.actor_key_id)
        audit_log(logger, action=action, request_id=rid, client_ip=ip, auth_result="allow", status="ok", actor_key_id=result.actor_key_id, reason="ok")
        return "ok"

    return _dependency


async def verify_admin_api_key(request: Request) -> str:
    return await require_admin_scope("admin")(request)
