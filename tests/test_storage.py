import asyncio

from app.infra.storage import FallbackStorage, MemoryStorage, RedisError


def test_memory_storage_idempotency() -> None:
    storage = MemoryStorage(idempotency_ttl=3600)

    first = asyncio.run(storage.is_duplicate_delivery("d-1"))
    second = asyncio.run(storage.is_duplicate_delivery("d-1"))

    assert first is False
    assert second is True


def test_memory_storage_stores_failed_payload() -> None:
    storage = MemoryStorage(idempotency_ttl=3600)

    failed_id = asyncio.run(
        storage.store_failed_delivery(
            source="github",
            event_type="push",
            payload={"repository": {"full_name": "org/repo"}},
            headers={"x-github-event": "push"},
            error="telegram failed",
            delivery_id="abc-123",
        )
    )

    assert failed_id in storage.failed_deliveries
    record = storage.failed_deliveries[failed_id]
    assert record["source"] == "github"
    assert record["event_type"] == "push"
    assert record["payload"]["repository"]["full_name"] == "org/repo"
    assert record["delivery_id"] == "abc-123"
    assert record["replay_attempts"] == 0
    assert record["last_replay_at"] is None
    assert record["last_replay_status"] is None


def test_memory_storage_replay_operation_idempotency() -> None:
    storage = MemoryStorage(idempotency_ttl=3600)

    first = asyncio.run(storage.is_duplicate_replay_operation("op-1", 60))
    second = asyncio.run(storage.is_duplicate_replay_operation("op-1", 60))

    assert first is False
    assert second is True


def test_memory_storage_delivery_ledger_metadata() -> None:
    storage = MemoryStorage(idempotency_ttl=3600)

    asyncio.run(storage.upsert_delivery_ledger("github", "d-1", "hash-a", "received"))
    entry = asyncio.run(storage.upsert_delivery_ledger("github", "d-1", "hash-a", "delivered"))

    assert entry["provider"] == "github"
    assert entry["inbound_delivery_id"] == "d-1"
    assert entry["payload_hash"] == "hash-a"
    assert entry["first_seen"]
    assert len(entry["status_transitions"]) == 2


class _FailingStorage:
    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        raise RedisError("down")

    async def store_failed_delivery(self, **kwargs) -> str:
        raise RedisError("down")

    async def is_duplicate_replay_operation(self, operation_key: str, ttl_seconds: int) -> bool:
        raise RedisError("down")

    async def list_failed_deliveries(self, source=None, status=None, limit=20, offset=0):
        raise RedisError("down")

    async def get_failed_delivery(self, failed_id: str):
        raise RedisError("down")

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        raise RedisError("down")

    async def update_failed_delivery(self, failed_id: str, updates) -> None:
        raise RedisError("down")

    async def upsert_delivery_ledger(
        self, provider: str, inbound_delivery_id: str, payload_hash: str, status: str, reason=None
    ):
        raise RedisError("down")

    async def get_delivery_ledger(self, provider: str, inbound_delivery_id: str):
        raise RedisError("down")


def test_fallback_storage_uses_memory_when_primary_fails() -> None:
    memory = MemoryStorage(idempotency_ttl=3600)
    storage = FallbackStorage(primary=_FailingStorage(), fallback=memory)

    assert storage.fallback_state()["active"] is False
    assert asyncio.run(storage.is_duplicate_delivery("dup-1")) is False
    assert asyncio.run(storage.is_duplicate_delivery("dup-1")) is True

    failed_id = asyncio.run(
        storage.store_failed_delivery(
            source="generic",
            event_type="generic",
            payload={"title": "Deploy"},
        )
    )
    assert failed_id in memory.failed_deliveries
    state = storage.fallback_state()
    assert state["active"] is True
    assert state["reason"] == "down"
    assert state["since"] is not None
