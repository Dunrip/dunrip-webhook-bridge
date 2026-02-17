import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.services.tg_client import TelegramSendError


pytestmark = pytest.mark.integration


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _redis_available() -> bool:
    try:
        import redis  # noqa: F401
        from redis.asyncio import Redis
    except Exception:
        return False

    async def _ping() -> bool:
        client = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
        try:
            await client.ping()
            return True
        except Exception:
            return False
        finally:
            await client.aclose()

    import asyncio

    return asyncio.run(_ping())


@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
def test_end_to_end_github_flow_with_redis_backend(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    monkeypatch.setattr(main.settings, "max_body_size", 1024 * 1024)
    monkeypatch.setattr(main.settings, "idempotency_ttl", 3600)
    monkeypatch.setattr(main.settings, "failed_delivery_ttl", 604800)
    monkeypatch.setattr(main.settings, "storage_backend", "redis")
    monkeypatch.setattr(main.settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(main.settings, "redis_key_prefix", "test:e2e")
    monkeypatch.setattr(main.settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_ip_per_minute", 10000)
    monkeypatch.setattr(main.settings, "rate_limit_token_per_minute", 10000)

    sent_messages: list[str] = []

    async def capture_send(msg: str) -> None:
        sent_messages.append(msg)

    monkeypatch.setattr(main, "send_message", capture_send)

    app = main.create_app()
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()

    with TestClient(app) as client:
        response = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload, "gh-secret"),
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "redis-e2e-1",
            },
        )
        assert response.status_code == 200
        assert sent_messages

        duplicate = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload, "gh-secret"),
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "redis-e2e-1",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["status"] == "duplicate"


@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
def test_end_to_end_failed_delivery_persisted(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "storage_backend", "redis")
    monkeypatch.setattr(main.settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(main.settings, "redis_key_prefix", "test:e2e:failed")
    monkeypatch.setattr(main.settings, "rate_limit_backend", "memory")

    async def fail_send(_: str) -> None:
        raise TelegramSendError("boom")

    monkeypatch.setattr(main, "send_message", fail_send)

    app = main.create_app()
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()

    with TestClient(app) as client:
        response = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload, "gh-secret"),
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "redis-fail-1",
            },
        )
        assert response.status_code == 502

        import asyncio

        rows, total = asyncio.run(
            client.app.state.storage.list_failed_deliveries(source="github", status="failed")
        )
        assert total >= 1
        assert rows[0]["source"] == "github"
