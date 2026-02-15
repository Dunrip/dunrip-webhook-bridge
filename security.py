"""Security helpers for webhook authentication and client identity.

This module centralizes signature verification, token/API-key validation,
and trusted-proxy-aware client IP resolution.
"""

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
from fastapi import Header, Request

from config import settings
from exceptions import AuthenticationError, ValidationError
from observability import audit_log, fingerprint_api_key

logger = logging.getLogger(__name__)

_VALID_SCOPES = {"read", "replay", "admin"}


@dataclass
class AdminAuthResult:
    ok: bool
    reason: str
    scope: str | None
    actor_key_id: str
    used_previous_key: bool = False


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse configured trusted proxy CIDR ranges.

    Returns:
        A list of trusted IPv4/IPv6 networks. Invalid entries are skipped.
    """
    raw = (settings.trusted_proxies or "").strip()
    if not raw:
        return []

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXIES entry: %s", candidate)
    return networks


def _is_trusted_proxy(
    ip: str,
    trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Check whether an IP belongs to a trusted proxy network."""
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(ip_obj in network for network in trusted_networks)


def get_client_ip(request: Request) -> str:
    """Determine the effective client IP address.

    If no trusted proxy networks are configured, the direct socket IP is used.
    When the direct peer is trusted, the rightmost X-Forwarded-For value is
    considered the client IP.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Best-effort client IP address string.
    """
    direct_ip = request.client.host if request.client else "unknown"

    trusted_networks = _trusted_proxy_networks()
    if not trusted_networks:
        return direct_ip

    if not _is_trusted_proxy(direct_ip, trusted_networks):
        return direct_ip

    forwarded_for = request.headers.get("x-forwarded-for")
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


def _compute_signature(body: bytes, secret: str) -> str:
    """Compute GitHub-style SHA256 HMAC signature for a payload body."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub webhook HMAC-SHA256 signature.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Raw request body bytes when validation succeeds.

    Raises:
        AuthenticationError: Signature header missing or invalid.
        ValidationError: Payload exceeds configured body-size limit.
    """
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("GitHub webhook missing signature header")
        raise AuthenticationError("Missing signature header", error_code="AUTH_MISSING_KEY")

    body = await request.body()

    if len(body) > settings.max_body_size:
        logger.warning(
            "GitHub webhook body too large: %d bytes (max %d)",
            len(body),
            settings.max_body_size,
        )
        raise ValidationError(
            "Payload too large",
            error_code="VALIDATION_ERROR",
            status_code=413,
        )

    expected = await anyio.to_thread.run_sync(
        partial(_compute_signature, body, settings.github_webhook_secret)
    )

    if not hmac.compare_digest(expected, signature_header):
        logger.warning("GitHub webhook signature validation failed")
        raise AuthenticationError("Invalid signature", error_code="WEBHOOK_INVALID_SIGNATURE")

    return body


def verify_generic_token(x_webhook_token: str | None = Header(default=None)) -> str:
    """Validate shared secret token for generic webhooks.

    Args:
        x_webhook_token: Value from X-Webhook-Token header.

    Returns:
        The validated token value.

    Raises:
        AuthenticationError: Token is missing or invalid.
    """
    if x_webhook_token is None:
        logger.warning("Generic webhook missing token header")
        raise AuthenticationError("Missing token header", error_code="AUTH_MISSING_KEY")

    if not hmac.compare_digest(x_webhook_token, settings.generic_webhook_token):
        logger.warning("Generic webhook token validation failed")
        raise AuthenticationError("Invalid token", error_code="AUTH_INVALID_KEY")
    return x_webhook_token


def _extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    """Extract API key from Authorization or X-API-Key header values."""
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
        if not pair:
            continue
        if ":" not in pair:
            logger.warning("Ignoring malformed admin key scope pair: %s", pair)
            continue
        key, scope = pair.split(":", 1)
        key = key.strip()
        scope = scope.strip().lower()
        if not key:
            continue
        if scope not in _VALID_SCOPES:
            logger.warning("Ignoring admin key with invalid scope '%s'", scope)
            continue
        parsed[key] = scope
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
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        logger.warning("Invalid ADMIN_KEY_ROTATION_STARTED_AT: %s", value)
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
    # New rotation-aware config takes priority when active is set.
    active = _parse_scoped_keys(settings.admin_api_keys_active)
    previous = _parse_scoped_keys(settings.admin_api_keys_previous)
    if active:
        return active, previous

    # Backward-compatible scoped map.
    scoped = _parse_scoped_keys(settings.admin_api_keys)
    if scoped:
        return scoped, {}

    # Legacy single key support.
    if settings.admin_api_key:
        return {settings.admin_api_key: "admin"}, {}

    return {}, {}


def authenticate_admin_api_key_headers(
    headers: Mapping[str, str],
    *,
    required_scope: str = "admin",
) -> AdminAuthResult:
    """Authenticate admin key and validate required scope."""
    provided = _extract_api_key(headers.get("authorization"), headers.get("x-api-key"))
    actor_key_id = fingerprint_api_key(provided)

    if provided is None:
        return AdminAuthResult(False, "missing", None, actor_key_id)

    active, previous = _resolve_admin_keys()
    if not active and not previous:
        return AdminAuthResult(False, "not_configured", None, actor_key_id)

    scope = active.get(provided)
    if scope:
        if _scope_allows(scope, required_scope):
            return AdminAuthResult(True, "ok", scope, actor_key_id)
        return AdminAuthResult(False, "expired_scope", scope, actor_key_id)

    prev_scope = previous.get(provided)
    if prev_scope:
        started_at = _parse_rotation_started_at(settings.admin_key_rotation_started_at)
        grace_seconds = max(int(settings.admin_key_rotation_grace_seconds), 0)
        if started_at is None or (time.time() - started_at) > grace_seconds:
            return AdminAuthResult(False, "expired_previous_key", prev_scope, actor_key_id, used_previous_key=True)
        if _scope_allows(prev_scope, required_scope):
            return AdminAuthResult(True, "ok", prev_scope, actor_key_id, used_previous_key=True)
        return AdminAuthResult(False, "expired_scope", prev_scope, actor_key_id, used_previous_key=True)

    return AdminAuthResult(False, "invalid", None, actor_key_id)


def validate_admin_api_key_headers(headers: Mapping[str, str]) -> bool:
    """Backwards-compatible boolean validator for admin endpoints."""
    return authenticate_admin_api_key_headers(headers, required_scope="admin").ok


def require_admin_scope(required_scope: str):
    async def _dependency(request: Request) -> str:
        request_id = getattr(request.state, "request_id", "-")
        client_ip = get_client_ip(request)
        action = f"{request.method} {request.url.path}"
        result = authenticate_admin_api_key_headers(request.headers, required_scope=required_scope)

        if result.used_previous_key and result.ok:
            logger.warning(
                "Admin auth accepted with previous key within grace window actor_key_id=%s scope=%s",
                result.actor_key_id,
                result.scope,
            )

        if result.reason == "not_configured":
            logger.error("Admin endpoint called but admin key config is missing")
            audit_log(
                logger,
                action=action,
                request_id=request_id,
                client_ip=client_ip,
                auth_result="error",
                status="admin_key_not_configured",
                actor_key_id=result.actor_key_id,
                reason=result.reason,
            )
            raise AuthenticationError(
                "Admin API key not configured",
                error_code="admin_key_not_configured",
                status_code=503,
            )

        if not result.ok:
            audit_log(
                logger,
                action=action,
                request_id=request_id,
                client_ip=client_ip,
                auth_result="deny",
                status="auth_failed",
                actor_key_id=result.actor_key_id,
                reason=result.reason,
            )
            if result.reason == "missing":
                raise AuthenticationError("Missing API key", error_code="missing")
            if result.reason == "expired_scope":
                raise AuthenticationError("Insufficient key scope", error_code="expired_scope", status_code=403)
            if result.reason == "expired_previous_key":
                raise AuthenticationError("Previous key expired", error_code="expired_previous_key", status_code=401)
            raise AuthenticationError("Invalid API key", error_code="invalid")

        audit_log(
            logger,
            action=action,
            request_id=request_id,
            client_ip=client_ip,
            auth_result="allow",
            status="ok",
            actor_key_id=result.actor_key_id,
            reason="ok",
        )
        return "ok"

    return _dependency


async def verify_admin_api_key(request: Request) -> str:
    """FastAPI dependency that enforces admin API-key authentication."""
    return await require_admin_scope("admin")(request)
