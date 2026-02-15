import hashlib
import hmac
import json

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

import security


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_client() -> TestClient:
    app = FastAPI()

    @app.post("/github")
    async def github(request: Request) -> dict[str, int]:
        body = await security.verify_github_signature(request)
        return {"size": len(body)}

    @app.post("/generic")
    async def generic(_token: str = Depends(security.verify_generic_token)) -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_verify_github_signature_valid(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "github_webhook_secret", "topsecret")
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
