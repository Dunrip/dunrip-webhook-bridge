import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import main
from tg_client import TelegramSendError


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    monkeypatch.setattr(main.settings, "max_body_size", 1024 * 1024)
    monkeypatch.setattr(main.settings, "idempotency_ttl", 3600)
    app = main.create_app()
    return TestClient(app)


def test_health(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_deep_success(monkeypatch) -> None:
    """Deep health check returns 200 when Telegram is accessible."""
    client = _client(monkeypatch)

    class FakeBot:
        async def get_me(self):
            class Me:
                username = "test_bot"
            return Me()

    # Mock the Bot import inside main module
    monkeypatch.setattr("telegram.Bot", lambda **kwargs: FakeBot())

    response = client.get("/health/deep")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["telegram"]["connected"] is True
    assert data["telegram"]["bot_username"] == "test_bot"


def test_health_deep_failure(monkeypatch) -> None:
    """Deep health check returns 503 when Telegram is unreachable."""
    client = _client(monkeypatch)

    from telegram.error import TelegramError

    class FakeBot:
        async def get_me(self):
            raise TelegramError("Network timeout")

    # Mock the Bot import inside main module
    monkeypatch.setattr("telegram.Bot", lambda **kwargs: FakeBot())

    response = client.get("/health/deep")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["telegram"]["connected"] is False


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
            "X-GitHub-Event": "star",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event": "star"}


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


def test_github_idempotency_duplicate_ignored(monkeypatch) -> None:
    """Duplicate deliveries with same X-GitHub-Delivery should be ignored."""
    client = _client(monkeypatch)
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()
    delivery_id = "abc-123-def"

    call_count = 0

    async def counting_send(_: str) -> None:
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(main, "send_message", counting_send)

    # First request
    response1 = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _sign(payload, "gh-secret"),
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": delivery_id,
        },
    )
    assert response1.status_code == 200
    assert response1.json()["status"] == "sent"
    assert call_count == 1

    # Duplicate request
    response2 = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _sign(payload, "gh-secret"),
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": delivery_id,
        },
    )
    assert response2.status_code == 200
    assert response2.json()["status"] == "duplicate"
    assert call_count == 1  # Should not increase


def test_github_release_event(monkeypatch) -> None:
    """Test release event formatter is called."""
    client = _client(monkeypatch)
    payload = json.dumps({
        "action": "published",
        "release": {"tag_name": "v1.0.0", "name": "Version 1.0"},
        "repository": {"full_name": "org/repo"},
    }).encode()

    sent_messages: list[str] = []

    async def capture_send(msg: str) -> None:
        sent_messages.append(msg)

    monkeypatch.setattr(main, "send_message", capture_send)

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _sign(payload, "gh-secret"),
            "X-GitHub-Event": "release",
        },
    )

    assert response.status_code == 200
    assert "*Release*" in sent_messages[0]
    # Tag is escaped for MarkdownV2 (v1\.0\.0)
    assert "v1\\.0\\.0" in sent_messages[0]


def test_github_workflow_run_event(monkeypatch) -> None:
    """Test workflow_run event formatter is called."""
    client = _client(monkeypatch)
    payload = json.dumps({
        "action": "completed",
        "workflow_run": {"conclusion": "success", "head_branch": "main"},
        "workflow": {"name": "CI"},
        "repository": {"full_name": "org/repo"},
    }).encode()

    sent_messages: list[str] = []

    async def capture_send(msg: str) -> None:
        sent_messages.append(msg)

    monkeypatch.setattr(main, "send_message", capture_send)

    response = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _sign(payload, "gh-secret"),
            "X-GitHub-Event": "workflow_run",
        },
    )

    assert response.status_code == 200
    assert "✅" in sent_messages[0]  # Success emoji
    assert "CI" in sent_messages[0]


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
