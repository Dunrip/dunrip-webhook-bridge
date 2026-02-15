import hashlib
import hmac
import json

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import security
from exceptions import WebhookError


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_client(client_host: str = "testclient") -> TestClient:
    app = FastAPI()

    @app.exception_handler(WebhookError)
    async def _webhook_error_handler(request: Request, exc: WebhookError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message})

    @app.post("/github")
    async def github(request: Request) -> dict[str, int]:
        body = await security.verify_github_signature(request)
        return {"size": len(body)}

    @app.post("/generic")
    async def generic(_token: str = Depends(security.verify_generic_token)) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/admin")
    async def admin(_token: str = Depends(security.verify_admin_api_key)) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client-ip")
    async def client_ip(request: Request) -> dict[str, str]:
        return {"ip": security.get_client_ip(request)}

    return TestClient(app, client=(client_host, 50000))


def test_verify_github_signature_valid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    monkeypatch.setattr(security.settings, "max_body_size", 1024 * 1024)
    client = _build_client()
    payload = json.dumps({"ok": True}).encode()

    response = client.post(
        "/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "topsecret")},
    )

    assert response.status_code == 200
    assert response.json() == {"size": len(payload)}


def test_verify_github_signature_missing_header(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    client = _build_client()

    response = client.post("/github", content=b"{}")

    assert response.status_code == 401
    assert response.json()["message"] == "Missing signature header"


def test_verify_github_signature_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    client = _build_client()

    response = client.post(
        "/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid signature"


def test_verify_github_signature_body_too_large(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    monkeypatch.setattr(security.settings, "max_body_size", 100)  # 100 bytes limit
    client = _build_client()

    payload = b"x" * 200  # Exceeds limit

    response = client.post(
        "/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "topsecret")},
    )

    assert response.status_code == 413
    assert response.json()["message"] == "Payload too large"


def test_verify_generic_token_valid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "generic_webhook_token", "abc123")
    client = _build_client()

    response = client.post("/generic", headers={"X-Webhook-Token": "abc123"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_generic_token_missing(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "generic_webhook_token", "abc123")
    client = _build_client()

    response = client.post("/generic")

    assert response.status_code == 401
    assert response.json()["message"] == "Missing token header"


def test_verify_generic_token_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "generic_webhook_token", "abc123")
    client = _build_client()

    response = client.post("/generic", headers={"X-Webhook-Token": "wrong"})

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid token"


def test_verify_admin_api_key_valid_x_api_key(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    client = _build_client()

    response = client.get("/admin", headers={"X-API-Key": "adminkey"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_admin_api_key_valid_authorization_bearer(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    client = _build_client()

    response = client.get("/admin", headers={"Authorization": "Bearer adminkey"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_admin_api_key_missing(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    client = _build_client()

    response = client.get("/admin")

    assert response.status_code == 401
    assert response.json()["message"] == "Missing API key"


def test_verify_admin_api_key_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    client = _build_client()

    response = client.get("/admin", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid API key"


def test_get_client_ip_ignores_xff_when_no_trusted_proxies(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "trusted_proxies", "")
    client = _build_client(client_host="192.0.2.20")

    response = client.get("/client-ip", headers={"X-Forwarded-For": "203.0.113.5"})

    assert response.status_code == 200
    assert response.json()["ip"] == "192.0.2.20"


def test_get_client_ip_uses_rightmost_xff_when_proxy_trusted(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "trusted_proxies", "192.0.2.0/24")
    client = _build_client(client_host="192.0.2.10")

    response = client.get(
        "/client-ip",
        headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.9"},
    )

    assert response.status_code == 200
    assert response.json()["ip"] == "203.0.113.9"


def test_get_client_ip_falls_back_when_proxy_untrusted(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "trusted_proxies", "192.0.2.10")
    client = _build_client(client_host="198.51.100.10")

    response = client.get("/client-ip", headers={"X-Forwarded-For": "203.0.113.5"})

    assert response.status_code == 200
    assert response.json()["ip"] == "198.51.100.10"


def test_get_client_ip_ignores_invalid_xff_ip(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "trusted_proxies", "192.0.2.0/24")
    client = _build_client(client_host="192.0.2.10")

    response = client.get("/client-ip", headers={"X-Forwarded-For": "not-an-ip"})

    assert response.status_code == 200
    assert response.json()["ip"] == "192.0.2.10"


def test_validate_admin_api_key_headers_accepts_raw_authorization(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")

    assert security.validate_admin_api_key_headers(
        {"authorization": "adminkey"}
    ) is True


def test_validate_admin_api_key_headers_prefers_x_api_key(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")

    assert security.validate_admin_api_key_headers(
        {"authorization": "Bearer wrong", "x-api-key": "adminkey"}
    ) is True


def test_verify_admin_api_key_unconfigured_returns_503(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "")
    client = _build_client()

    response = client.get("/admin", headers={"X-API-Key": "anything"})

    assert response.status_code == 503
    assert response.json()["message"] == "Admin API key not configured"


def test_scoped_admin_keys_enforce_scope(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    monkeypatch.setattr(
        security.settings,
        "admin_api_keys",
        "read-key:read,replay-key:replay,admin-key:admin",
    )

    read_auth = security.authenticate_admin_api_key_headers(
        {"x-api-key": "read-key"}, required_scope="read"
    )
    replay_auth = security.authenticate_admin_api_key_headers(
        {"x-api-key": "read-key"}, required_scope="replay"
    )
    admin_auth = security.authenticate_admin_api_key_headers(
        {"x-api-key": "admin-key"}, required_scope="replay"
    )

    assert read_auth.ok is True
    assert read_auth.scope == "read"
    assert replay_auth.ok is False
    assert replay_auth.reason == "expired_scope"
    assert admin_auth.ok is True


def test_rotation_previous_key_accepted_within_grace(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "new-key:admin")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "old-key:admin")
    monkeypatch.setattr(security.settings, "admin_key_rotation_grace_seconds", 3600)
    monkeypatch.setattr(security.settings, "admin_key_rotation_started_at", str(1_000_000_000))
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000_100)

    result = security.authenticate_admin_api_key_headers(
        {"x-api-key": "old-key"}, required_scope="admin"
    )

    assert result.ok is True
    assert result.used_previous_key is True


def test_rotation_previous_key_rejected_after_grace(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "new-key:admin")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "old-key:admin")
    monkeypatch.setattr(security.settings, "admin_key_rotation_grace_seconds", 10)
    monkeypatch.setattr(security.settings, "admin_key_rotation_started_at", str(1_000_000_000))
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000_100)

    result = security.authenticate_admin_api_key_headers(
        {"x-api-key": "old-key"}, required_scope="admin"
    )

    assert result.ok is False
    assert result.reason == "expired_previous_key"


def test_legacy_admin_api_key_backward_compatible(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "")
    monkeypatch.setattr(security.settings, "admin_api_key", "legacy-key")

    result = security.authenticate_admin_api_key_headers(
        {"authorization": "Bearer legacy-key"}, required_scope="admin"
    )

    assert result.ok is True
    assert result.scope == "admin"
