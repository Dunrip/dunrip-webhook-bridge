import json
import logging

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.infra.storage import MemoryStorage
from app.services.tg_client import TelegramSendError


def _client(monkeypatch, client_host: str = "testclient") -> TestClient:
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
    monkeypatch.setattr(main.settings, "rate_limit_admin_per_minute", 1000)
    monkeypatch.setattr(main.settings, "replay_cooldown_seconds", 30)
    monkeypatch.setattr(main.settings, "max_replay_attempts", 10)
    monkeypatch.setattr(main.settings, "ws_connects_per_minute", 1000)
    monkeypatch.setattr(main.settings, "ws_max_connections_per_ip", 1000)
    monkeypatch.setattr(main.settings, "trusted_proxies", "")
    monkeypatch.setattr(main.settings, "admin_ip_allowlist", "")
    monkeypatch.setattr(main.settings, "ws_ip_allowlist", "")
    from app.infra.circuit_breaker import telegram_circuit
    telegram_circuit._reset()
    app = main.create_app()
    # TestClient only runs lifespan when used as a context manager; these tests
    # instantiate it directly, so initialize shared app.state dependencies here.
    main._initialize_app_state(app)
    client = TestClient(app, client=(client_host, 50000))
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
        headers={"x-request-id": "gen-del-1"},
        error="Telegram rate limited",
        delivery_id="gen-del-1",
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


def test_list_deliveries_requires_auth(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client = _client(monkeypatch)
    response = client.get("/deliveries", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid API key"
    assert "admin_audit" in caplog.text
    assert "auth_result=deny" in caplog.text


def test_list_deliveries_logs_success_audit(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client = _client(monkeypatch)
    response = client.get("/deliveries")
    assert response.status_code == 200
    assert "admin_audit" in caplog.text
    assert "auth_result=allow" in caplog.text


def test_list_deliveries_accepts_read_scope_key(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(main.settings, "admin_api_key", "")
    monkeypatch.setattr(main.settings, "admin_api_keys", "read-only:read,replay-only:replay")

    response = client.get("/deliveries", headers={"X-API-Key": "read-only"})
    assert response.status_code == 200


def test_replay_requires_replay_scope(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(main.settings, "admin_api_key", "")
    monkeypatch.setattr(main.settings, "admin_api_keys", "read-only:read,replay-only:replay")
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def ok_send(_: str) -> None:
        return None

    import app.api.replay as replay
    monkeypatch.setattr(replay, "send_message", ok_send)

    denied = client.post(f"/deliveries/{ids[0]}/replay", headers={"X-API-Key": "read-only"})
    assert denied.status_code == 403

    allowed = client.post(f"/deliveries/{ids[0]}/replay", headers={"X-API-Key": "replay-only"})
    assert allowed.status_code == 200


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
    import app.api.replay as replay
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
    assert response.json()["message"] == "Delivery not found"


def test_replay_delivery_telegram_failure(monkeypatch) -> None:
    """Replay keeps 'failed' status if Telegram send fails again."""
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def fail_send(_: str) -> None:
        raise TelegramSendError("still broken")

    monkeypatch.setattr(main, "send_message", fail_send)
    import app.api.replay as replay
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
    import app.api.replay as replay
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
    import app.api.replay as replay
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
    import app.api.replay as replay
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


def test_replay_cooldown_enforced(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(main.settings, "replay_cooldown_seconds", 60)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def fail_send(_: str) -> None:
        raise TelegramSendError("still failing")

    import app.api.replay as replay
    monkeypatch.setattr(replay, "send_message", fail_send)

    first = client.post(f"/deliveries/{ids[0]}/replay")
    assert first.status_code == 200
    second = client.post(f"/deliveries/{ids[0]}/replay")
    assert second.status_code == 429
    assert second.json()["error"] == "replay_cooldown_active"


def test_replay_idempotency_key_blocks_duplicates(monkeypatch) -> None:
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def ok_send(_: str) -> None:
        return None

    import app.api.replay as replay
    monkeypatch.setattr(replay, "send_message", ok_send)

    headers = {"Idempotency-Key": "abc", "X-API-Key": "admin-test-key"}
    first = client.post(f"/deliveries/{ids[0]}/replay", headers=headers)
    assert first.status_code == 200
    second = client.post(f"/deliveries/{ids[0]}/replay", headers=headers)
    assert second.status_code == 409
    assert second.json()["error"] == "replay_duplicate_request"


def test_replay_max_attempts_moves_to_dead_letter(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(main.settings, "max_replay_attempts", 1)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def fail_send(_: str) -> None:
        raise TelegramSendError("boom")

    import app.api.replay as replay
    monkeypatch.setattr(replay, "send_message", fail_send)

    response = client.post(f"/deliveries/{ids[0]}/replay")
    assert response.status_code == 200
    assert response.json()["status"] == "dead_letter"
    assert storage.failed_deliveries[ids[0]]["status"] == "dead_letter"


def test_deliveries_allowlist_blocks_non_matching_ip(monkeypatch) -> None:
    client = _client(monkeypatch, client_host="198.51.100.10")
    monkeypatch.setattr(main.settings, "admin_ip_allowlist", "203.0.113.0/24")
    monkeypatch.setattr(main.settings, "trusted_proxies", "")

    response = client.get("/deliveries")

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"] == "ADMIN_IP_NOT_ALLOWED"
    assert payload["request_id"]


def test_deliveries_allowlist_allows_matching_ip(monkeypatch) -> None:
    client = _client(monkeypatch, client_host="203.0.113.10")
    monkeypatch.setattr(main.settings, "admin_ip_allowlist", "203.0.113.0/24")
    monkeypatch.setattr(main.settings, "trusted_proxies", "")

    response = client.get("/deliveries")

    assert response.status_code == 200


def test_deliveries_allowlist_respects_trusted_proxy_xff(monkeypatch) -> None:
    client = _client(monkeypatch, client_host="198.51.100.10")
    monkeypatch.setattr(main.settings, "admin_ip_allowlist", "203.0.113.0/24")
    monkeypatch.setattr(main.settings, "trusted_proxies", "198.51.100.0/24")

    response = client.get("/deliveries", headers={"X-Forwarded-For": "203.0.113.9"})

    assert response.status_code == 200

def test_replay_safety_blocks_already_delivered_ledger(monkeypatch) -> None:
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    import asyncio
    asyncio.run(storage.upsert_delivery_ledger("github", "gh-del-1", "hash-x", "delivered"))

    response = client.post(f"/deliveries/{ids[0]}/replay")
    assert response.status_code == 409
    assert response.json()["error"] == "replay_already_delivered"


def test_replay_generic_safety_blocks_already_delivered_ledger(monkeypatch) -> None:
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    import asyncio
    generic_record = storage.failed_deliveries[ids[1]]
    generic_delivery_id = generic_record["delivery_id"]
    asyncio.run(storage.upsert_delivery_ledger("generic", generic_delivery_id, "hash-x", "delivered"))

    response = client.post(f"/deliveries/{ids[1]}/replay")
    assert response.status_code == 409
    assert response.json()["error"] == "replay_already_delivered"


def test_replay_updates_ledger_to_delivered(monkeypatch) -> None:
    client = _client(monkeypatch)
    storage = client.app.state.storage
    ids = _seed_failures(storage)

    async def ok_send(_: str) -> None:
        return None

    import asyncio
    import app.api.replay as replay
    monkeypatch.setattr(replay, "send_message", ok_send)
    asyncio.run(storage.upsert_delivery_ledger("github", "gh-del-1", "hash-x", "failed", "delivery_failed"))

    response = client.post(f"/deliveries/{ids[0]}/replay")
    assert response.status_code == 200
    ledger = asyncio.run(storage.get_delivery_ledger("github", "gh-del-1"))
    assert ledger is not None
    assert ledger["status"] == "delivered"
