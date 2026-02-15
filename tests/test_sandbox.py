import json

import pytest
from fastapi.testclient import TestClient

import main


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    monkeypatch.setattr(main.settings, "max_body_size", 1024 * 1024)
    monkeypatch.setattr(main.settings, "idempotency_ttl", 3600)
    monkeypatch.setattr(main.settings, "failed_delivery_ttl", 604800)
    monkeypatch.setattr(main.settings, "storage_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_ip_per_minute", 1000)
    monkeypatch.setattr(main.settings, "rate_limit_token_per_minute", 1000)
    from circuit_breaker import telegram_circuit
    telegram_circuit._reset()
    app = main.create_app()
    return TestClient(app)


def test_github_sandbox_push(monkeypatch) -> None:
    """Sandbox returns formatted push message without sending to Telegram."""
    client = _client(monkeypatch)

    async def fail_send(_: str) -> None:
        raise AssertionError("send_message must NOT be called in sandbox")

    monkeypatch.setattr(main, "send_message", fail_send)

    payload = {
        "repository": {"full_name": "org/repo"},
        "pusher": {"name": "alice"},
        "ref": "refs/heads/main",
        "commits": [{"id": "abc1234567", "message": "first commit"}],
        "compare": "https://github.com/org/repo/compare/abc...def",
    }

    response = client.post(
        "/webhook/github/sandbox",
        content=json.dumps(payload).encode(),
        headers={"X-GitHub-Event": "push"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["preview"] is not None
    assert "*Push*" in data["preview"]
    assert data["payload_summary"]["event_type"] == "push"
    assert data["payload_summary"]["repository"] == "org/repo"
    assert data["payload_summary"]["commit_count"] == 1
    assert data["payload_summary"]["branch"] == "main"


def test_github_sandbox_pr(monkeypatch) -> None:
    """Sandbox returns formatted PR message."""
    client = _client(monkeypatch)

    payload = {
        "action": "opened",
        "pull_request": {
            "title": "Add feature",
            "number": 42,
            "user": {"login": "bob"},
            "html_url": "https://github.com/org/repo/pull/42",
        },
        "repository": {"full_name": "org/repo"},
    }

    response = client.post(
        "/webhook/github/sandbox",
        content=json.dumps(payload).encode(),
        headers={"X-GitHub-Event": "pull_request"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "*Pull Request*" in data["preview"]
    assert data["payload_summary"]["number"] == 42
    assert data["payload_summary"]["title"] == "Add feature"


def test_github_sandbox_unsupported_event(monkeypatch) -> None:
    """Sandbox returns null preview for unsupported events."""
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/github/sandbox",
        content=b"{}",
        headers={"X-GitHub-Event": "star"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["preview"] is None
    assert data["payload_summary"]["event_type"] == "star"


def test_github_sandbox_malformed_json(monkeypatch) -> None:
    """Sandbox returns 400 for malformed JSON."""
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/github/sandbox",
        content=b"{bad",
        headers={"X-GitHub-Event": "push"},
    )

    assert response.status_code == 400


def test_github_sandbox_non_object_payload(monkeypatch) -> None:
    """Sandbox returns 400 for non-object payload."""
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/github/sandbox",
        content=b"[]",
        headers={"X-GitHub-Event": "push"},
    )

    assert response.status_code == 400


def test_generic_sandbox(monkeypatch) -> None:
    """Generic sandbox returns formatted message without sending."""
    client = _client(monkeypatch)

    async def fail_send(_: str) -> None:
        raise AssertionError("send_message must NOT be called in sandbox")

    monkeypatch.setattr(main, "send_message", fail_send)

    response = client.post(
        "/webhook/generic/sandbox",
        json={"title": "Deploy", "body": "Production deploy complete", "url": "https://example.com"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "Deploy" in data["preview"]
    assert data["payload_summary"]["event_type"] == "generic"
    assert data["payload_summary"]["title"] == "Deploy"
    assert data["payload_summary"]["url"] == "https://example.com"


def test_generic_sandbox_no_url(monkeypatch) -> None:
    """Generic sandbox works without URL."""
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/generic/sandbox",
        json={"title": "Alert", "body": "Something happened"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "url" not in data["payload_summary"]


def test_generic_sandbox_invalid_payload(monkeypatch) -> None:
    """Generic sandbox validates payload."""
    client = _client(monkeypatch)

    response = client.post(
        "/webhook/generic/sandbox",
        json={"title": "", "body": "ok"},
    )

    assert response.status_code == 422
