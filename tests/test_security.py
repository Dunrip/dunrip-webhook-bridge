import hashlib
import hmac
import json
import time

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
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message, "error": exc.error_code})

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

    @app.get("/admin-read")
    async def admin_read(_token: str = Depends(security.require_admin_scope("read"))) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/admin-replay")
    async def admin_replay(_token: str = Depends(security.require_admin_scope("replay"))) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client-ip")
    async def client_ip(request: Request) -> dict[str, str]:
        return {"ip": security.get_client_ip(request)}

    return TestClient(app, client=(client_host, 50000))


def test_verify_admin_scope_and_rotation(monkeypatch):
    monkeypatch.setattr(security.settings, "admin_api_keys", "readkey:read,replaykey:replay")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "")
    client = _build_client()
    assert client.get("/admin-read", headers={"X-API-Key": "readkey"}).status_code == 200
    assert client.get("/admin-replay", headers={"X-API-Key": "readkey"}).status_code == 403

    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "active:admin")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "old:admin")
    monkeypatch.setattr(security.settings, "admin_key_rotation_started_at", str(time.time() - 3600))
    monkeypatch.setattr(security.settings, "admin_key_rotation_grace_seconds", 60)
    resp = client.get("/admin", headers={"X-API-Key": "old"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "expired_previous_key"


def test_legacy_admin_key_backcompat(monkeypatch):
    monkeypatch.setattr(security.settings, "admin_api_keys", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "")
    monkeypatch.setattr(security.settings, "admin_api_key", "legacy")
    client = _build_client()
    assert client.get("/admin", headers={"X-API-Key": "legacy"}).status_code == 200


def test_admin_api_keys_single_key_equivalent_to_legacy(monkeypatch):
    monkeypatch.setattr(security.settings, "admin_api_keys", "single-admin-key")
    monkeypatch.setattr(security.settings, "admin_api_keys_active", "")
    monkeypatch.setattr(security.settings, "admin_api_keys_previous", "")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    client = _build_client()
    assert client.get("/admin", headers={"X-API-Key": "single-admin-key"}).status_code == 200


def test_verify_github_signature_valid(monkeypatch):
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
    monkeypatch.setattr(security.settings, "max_body_size", 1024 * 1024)
    client = _build_client()
    payload = json.dumps({"ok": True}).encode()
    response = client.post("/github", content=payload, headers={"X-Hub-Signature-256": _sign(payload, "topsecret")})
    assert response.status_code == 200


def test_verify_generic_token_invalid(monkeypatch):
    monkeypatch.setattr(security.settings, "generic_webhook_token", "abc123")
    client = _build_client()
    response = client.post("/generic", headers={"X-Webhook-Token": "wrong"})
    assert response.status_code == 401


def test_validate_admin_api_key_headers_prefers_x_api_key(monkeypatch):
    monkeypatch.setattr(security.settings, "admin_api_keys", "adminkey:admin")
    monkeypatch.setattr(security.settings, "admin_api_key", "")
    assert security.validate_admin_api_key_headers({"authorization": "Bearer wrong", "x-api-key": "adminkey"}) is True
