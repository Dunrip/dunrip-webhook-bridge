import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import main
from tg_client import TelegramSendError


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    app = main.create_app()
    return TestClient(app)


def test_health(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_github_ping(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = b"{}"

    async def fake_send(_: str) -> None:
        raise AssertionError("send_message should not be called for ping")

    monkeypatch.setattr(main, "send_message", fake_send)

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "gh-secret"), "X-GitHub-Event": "ping"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "pong"}


def test_github_unsupported_event(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = b"{}"

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _sign(payload, "gh-secret"),
            "X-GitHub-Event": "release",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event": "release"}


def test_github_malformed_json(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = b"{bad"

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "gh-secret"), "X-GitHub-Event": "push"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Malformed JSON payload"


def test_github_invalid_signature(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=wrong", "X-GitHub-Event": "push"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


def test_github_payload_must_be_object(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = b"[]"

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "gh-secret"), "X-GitHub-Event": "push"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Payload must be a JSON object"


def test_github_send_failure_returns_502(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()

    async def fail_send(_: str) -> None:
        raise TelegramSendError("boom")

    monkeypatch.setattr(main, "send_message", fail_send)

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": _sign(payload, "gh-secret"), "X-GitHub-Event": "push"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to deliver message"


def test_generic_success(monkeypatch) -> None:
    client = _client(monkeypatch)
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(main, "send_message", fake_send)

    response = client.post(
        "/webhook/generic",
        headers={"X-Webhook-Token": "generic-token"},
        json={"title": "Deploy", "body": "Done", "url": "https://example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    assert sent


def test_generic_missing_token(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/webhook/generic", json={"title": "A", "body": "B"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing token header"


def test_generic_invalid_payload(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/webhook/generic",
        headers={"X-Webhook-Token": "generic-token"},
        json={"title": "", "body": "ok"},
    )
    assert response.status_code == 422


def test_generic_send_failure_returns_502(monkeypatch) -> None:
    client = _client(monkeypatch)

    async def fail_send(_: str) -> None:
        raise TelegramSendError("fail")

    monkeypatch.setattr(main, "send_message", fail_send)

    response = client.post(
        "/webhook/generic",
        headers={"X-Webhook-Token": "generic-token"},
        json={"title": "Deploy", "body": "failed"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to deliver message"
