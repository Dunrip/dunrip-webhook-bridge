import json

import pytest
from fastapi.testclient import TestClient

import main
from storage import MemoryStorage
from tg_client import TelegramSendError


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    monkeypatch.setattr(main.settings, "admin_api_key", "admin-test-key")
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
    # TestClient only runs lifespan when used as a context manager; these tests
    # instantiate it directly, so initialize shared app.state dependencies here.
    main._initialize_app_state(app)
    client = TestClient(app)
    client.headers.update({"X-API-Key": "admin-test-key"})
    return client


def _seed_failures(storage: MemoryStorage) -> list[str]:
    """Seed storage with failed deliveries. Returns list of IDs."""
    import asyncio
    ids = []
    loop = asyncio.new_event_loop()

    fid = loop.run_until_complete(storage.store_failed_delivery(
        source="github",
        event_type="push",
        payload={"repository": {"full_name": "org/repo"}, "commits": [], "pusher": {"name": "alice"}, "ref": "refs/heads/main"},
        headers={"x-github-event": "push"},
        error="Telegram network error",
        delivery_id="gh-del-1",
    ))
    ids.append(fid)

    fid = loop.run_until_complete(storage.store_failed_delivery(
        source="generic",
        event_type="generic",
        payload={"title": "Deploy", "body": "Failed deploy"},
        headers={},
        error="Telegram rate limited",
    ))
    ids.append(fid)

    fid = loop.run_until_complete(storage.store_failed_delivery(
        source="github",
        event_type="pull_request",
        payload={
            "action": "opened",
            "pull_request": {"title": "Fix", "number": 1, "user": {"login": "bob"}, "html_url": ""},
            "repository": {"full_name": "org/repo"},
        },
        headers={"x-github-event": "pull_request"},
        error="Circuit breaker open",
    ))
    ids.append(fid)

    loop.close()
    return ids


def test_list_deliveries_requires_auth(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/deliveries", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_list_deliveries_empty(monkeypatch) -> None:
    """List deliveries returns empty list when no failures."""
    client = _client(monkeypatch)
    response = client.get("/deliveries")
    assert response.status_code == 200
    data = response.json()
    assert data["deliveries"] == []
    assert data["total"] == 0


def test_list_deliveries_with_failures(monkeypatch) -> None:
    """List deliveries returns stored failures."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    response = client.get("/deliveries")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["deliveries"]) == 3


def test_list_deliveries_filter_by_source(monkeypatch) -> None:
    """List deliveries can filter by source."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    _seed_failures(storage)

    response = client.get("/deliveries?source=github")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(d["source"] == "github" for d in data["deliveries"])


def test_list_deliveries_filter_by_status(monkeypatch) -> None:
    """List deliveries can filter by status."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    _seed_failures(storage)

    response = client.get("/deliveries?status=failed")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3  # all are failed initially


def test_list_deliveries_pagination(monkeypatch) -> None:
    """List deliveries supports limit and offset."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    _seed_failures(storage)

    response = client.get("/deliveries?limit=2&offset=0")
    data = response.json()
    assert len(data["deliveries"]) == 2
    assert data["total"] == 3

    response2 = client.get("/deliveries?limit=2&offset=2")
    data2 = response2.json()
    assert len(data2["deliveries"]) == 1
    assert data2["total"] == 3


def test_replay_delivery_success(monkeypatch) -> None:
    """Replay a failed delivery successfully."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(main, "send_message", fake_send)
    # Also patch in replay module
    import replay
    monkeypatch.setattr(replay, "send_message", fake_send)

    response = client.post(f"/deliveries/{ids[0]}/replay")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "delivered"
    assert data["delivery_id"] == ids[0]
    assert len(sent) == 1

    # Verify status was updated in storage
    assert storage.failed_deliveries[ids[0]]["status"] == "delivered"


def test_replay_delivery_not_found(monkeypatch) -> None:
    """Replay returns 404 for unknown delivery ID."""
    client = _client(monkeypatch)

    response = client.post("/deliveries/nonexistent-id/replay")
    assert response.status_code == 404
    assert response.json()["detail"] == "Delivery not found"


def test_replay_delivery_telegram_failure(monkeypatch) -> None:
    """Replay keeps 'failed' status if Telegram send fails again."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def fail_send(_: str) -> None:
        raise TelegramSendError("still broken")

    monkeypatch.setattr(main, "send_message", fail_send)
    import replay
    monkeypatch.setattr(replay, "send_message", fail_send)

    response = client.post(f"/deliveries/{ids[0]}/replay")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"

    # Status unchanged
    assert storage.failed_deliveries[ids[0]]["status"] == "failed"


def test_replay_generic_delivery(monkeypatch) -> None:
    """Replay a generic failed delivery."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(main, "send_message", fake_send)
    import replay
    monkeypatch.setattr(replay, "send_message", fake_send)

    # ids[1] is the generic delivery
    response = client.post(f"/deliveries/{ids[1]}/replay")
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"
    assert "Deploy" in sent[0]


def test_replay_all_success(monkeypatch) -> None:
    """Replay all retries all failed deliveries."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(main, "send_message", fake_send)
    import replay
    monkeypatch.setattr(replay, "send_message", fake_send)

    response = client.post("/deliveries/replay-all")
    assert response.status_code == 200
    data = response.json()
    assert data["attempted"] == 3
    assert data["succeeded"] == 3
    assert data["failed"] == 0
    assert len(sent) == 3


def test_replay_all_partial_failure(monkeypatch) -> None:
    """Replay all handles mixed success/failure."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    call_count = 0

    async def sometimes_fail(text: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TelegramSendError("fail on second")

    monkeypatch.setattr(main, "send_message", sometimes_fail)
    import replay
    monkeypatch.setattr(replay, "send_message", sometimes_fail)

    response = client.post("/deliveries/replay-all")
    assert response.status_code == 200
    data = response.json()
    assert data["attempted"] == 3
    assert data["succeeded"] == 2
    assert data["failed"] == 1


def test_replay_all_empty(monkeypatch) -> None:
    """Replay all with no failures returns zeros."""
    client = _client(monkeypatch)

    response = client.post("/deliveries/replay-all")
    assert response.status_code == 200
    data = response.json()
    assert data["attempted"] == 0
    assert data["succeeded"] == 0
    assert data["failed"] == 0


def test_replay_unknown_event_formatter_is_counted_as_failed(monkeypatch) -> None:
    """Unknown event types should not crash replay and should be counted as failed."""
    client = _client(monkeypatch)
    storage = client.app.state.storage

    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(storage.store_failed_delivery(
        source="github",
        event_type="fork",  # no registered formatter
        payload={"repository": {"full_name": "org/repo"}},
        headers={"x-github-event": "fork"},
        error="initial failure",
    ))
    loop.close()

    response = client.post("/deliveries/replay-all")
    assert response.status_code == 200
    data = response.json()
    assert data["attempted"] == 1
    assert data["succeeded"] == 0
    assert data["failed"] == 1
