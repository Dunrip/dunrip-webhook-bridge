import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.performance
def test_webhook_processing_light_benchmark(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "storage_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_ip_per_minute", 100000)
    monkeypatch.setattr(main.settings, "rate_limit_token_per_minute", 100000)

    async def fake_send(_: str) -> None:
        return None

    monkeypatch.setattr(main, "send_message", fake_send)

    app = main.create_app()
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()
    n = 50

    with TestClient(app) as client:
        started = time.perf_counter()
        for i in range(n):
            response = client.post(
                "/webhook/github",
                content=payload,
                headers={
                    "X-Hub-Signature-256": _sign(payload, "gh-secret"),
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": f"perf-{i}",
                },
            )
            assert response.status_code == 200
        elapsed = time.perf_counter() - started

    avg_ms = (elapsed / n) * 1000
    # Broad threshold for CI/dev laptops: keep regression signal without flakiness.
    assert avg_ms < 100, f"average webhook processing time too high: {avg_ms:.2f}ms"
