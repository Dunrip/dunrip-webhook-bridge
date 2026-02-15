import hashlib
import hmac
import json

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

import security


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_client(client_host: str = "testclient") -> TestClient:
    app = FastAPI()

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
    assert response.json()["detail"] == "Missing signature header"


def test_verify_github_signature_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    client = _build_client()

    response = client.post(
        "/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


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
    assert response.json()["detail"] == "Payload too large"


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
    assert response.json()["detail"] == "Missing token header"


def test_verify_generic_token_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "generic_webhook_token", "abc123")
    client = _build_client()

    response = client.post("/generic", headers={"X-Webhook-Token": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_verify_admin_api_key_valid_x_api_key(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "adminkey")
    client = _build_client()

    response = client.get("/admin", headers={"X-API-Key": "adminkey"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_admin_api_key_valid_authorization_bearer(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "adminkey")
    client = _build_client()

    response = client.get("/admin", headers={"Authorization": "Bearer adminkey"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_admin_api_key_missing(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "adminkey")
    client = _build_client()

    response = client.get("/admin")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


def test_verify_admin_api_key_invalid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "admin_api_key", "adminkey")
    client = _build_client()

    response = client.get("/admin", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


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
