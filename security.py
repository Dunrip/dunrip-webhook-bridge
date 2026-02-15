import hashlib
import hmac
import ipaddress
import logging
from collections.abc import Mapping
from functools import partial

import anyio
from fastapi import Header, HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
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
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(ip_obj in network for network in trusted_networks)


def get_client_ip(request: Request) -> str:
    """Securely determine client IP, trusting X-Forwarded-For only from trusted proxies."""
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
    """Synchronous HMAC computation (run in thread pool)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub webhook HMAC-SHA256 signature. Returns raw body."""
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("GitHub webhook missing signature header")
        raise HTTPException(status_code=401, detail="Missing signature header")

    body = await request.body()

    # Body size limit
    if len(body) > settings.max_body_size:
        logger.warning(
            "GitHub webhook body too large: %d bytes (max %d)",
            len(body),
            settings.max_body_size,
        )
        raise HTTPException(status_code=413, detail="Payload too large")

    # Run HMAC in thread pool to avoid blocking event loop
    expected = await anyio.to_thread.run_sync(
        partial(_compute_signature, body, settings.github_webhook_secret)
    )

    if not hmac.compare_digest(expected, signature_header):
        logger.warning("GitHub webhook signature validation failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    return body


def verify_generic_token(x_webhook_token: str | None = Header(default=None)) -> str:
    """Validate bearer token for generic webhooks."""
    if x_webhook_token is None:
        logger.warning("Generic webhook missing token header")
        raise HTTPException(status_code=401, detail="Missing token header")

    if not hmac.compare_digest(x_webhook_token, settings.generic_webhook_token):
        logger.warning("Generic webhook token validation failed")
        raise HTTPException(status_code=401, detail="Invalid token")
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


def validate_admin_api_key_headers(headers: Mapping[str, str]) -> bool:
    """Validate admin API key from Authorization or X-API-Key headers."""
    expected = settings.admin_api_key
    if not expected:
        return False

    provided = _extract_api_key(
        headers.get("authorization"),
        headers.get("x-api-key"),
    )
    return bool(provided) and hmac.compare_digest(provided, expected)


async def verify_admin_api_key(request: Request) -> str:
    """Dependency for admin endpoints protected by API key."""
    if not settings.admin_api_key:
        logger.error("Admin endpoint called but ADMIN_API_KEY is not configured")
        raise HTTPException(status_code=503, detail="Admin API key not configured")

    if not validate_admin_api_key_headers(request.headers):
        provided = _extract_api_key(
            request.headers.get("authorization"),
            request.headers.get("x-api-key"),
        )
        if provided is None:
            logger.warning("Admin endpoint missing API key")
            raise HTTPException(status_code=401, detail="Missing API key")
        logger.warning("Admin endpoint invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    return "ok"
