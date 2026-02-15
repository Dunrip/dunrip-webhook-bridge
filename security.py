"""Security helpers for webhook authentication and client identity.

This module centralizes signature verification, token/API-key validation,
and trusted-proxy-aware client IP resolution.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
from collections.abc import Mapping
from functools import partial

import anyio
from fastapi import Header, Request

from config import settings
from exceptions import AuthenticationError, ValidationError
from observability import audit_log, fingerprint_api_key

logger = logging.getLogger(__name__)


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


def validate_admin_api_key_headers(headers: Mapping[str, str]) -> bool:
    """Validate admin API key from request headers.

    Args:
        headers: Header mapping containing authorization values.

    Returns:
        True when a configured admin key is present and matches; otherwise False.
    """
    expected = settings.admin_api_key
    if not expected:
        return False

    provided = _extract_api_key(
        headers.get("authorization"),
        headers.get("x-api-key"),
    )
    return bool(provided) and hmac.compare_digest(provided, expected)


async def verify_admin_api_key(request: Request) -> str:
    """FastAPI dependency that enforces admin API-key authentication.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Constant success marker when authentication succeeds.

    Raises:
        AuthenticationError: API key is missing, invalid, or misconfigured.
    """
    request_id = getattr(request.state, "request_id", "-")
    client_ip = get_client_ip(request)
    action = f"{request.method} {request.url.path}"
    provided = _extract_api_key(
        request.headers.get("authorization"),
        request.headers.get("x-api-key"),
    )
    actor = fingerprint_api_key(provided)

    if not settings.admin_api_key:
        logger.error("Admin endpoint called but ADMIN_API_KEY is not configured")
        audit_log(
            logger,
            action=action,
            request_id=request_id,
            client_ip=client_ip,
            auth_result="error",
            status="admin_key_not_configured",
            actor=actor,
        )
        raise AuthenticationError(
            "Admin API key not configured",
            error_code="admin_key_not_configured",
            status_code=503,
        )

    if not validate_admin_api_key_headers(request.headers):
        if provided is None:
            logger.warning("Admin endpoint missing API key")
            audit_log(
                logger,
                action=action,
                request_id=request_id,
                client_ip=client_ip,
                auth_result="deny",
                status="missing_api_key",
                actor="api-key",
            )
            raise AuthenticationError("Missing API key", error_code="AUTH_MISSING_KEY")
        logger.warning("Admin endpoint invalid API key")
        audit_log(
            logger,
            action=action,
            request_id=request_id,
            client_ip=client_ip,
            auth_result="deny",
            status="invalid_api_key",
            actor=actor,
        )
        raise AuthenticationError("Invalid API key", error_code="AUTH_INVALID_KEY")

    audit_log(
        logger,
        action=action,
        request_id=request_id,
        client_ip=client_ip,
        auth_result="allow",
        status="ok",
        actor=actor,
    )
    return "ok"
