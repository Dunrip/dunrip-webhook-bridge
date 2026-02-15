import asyncio

from storage import FallbackStorage, MemoryStorage, RedisError


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


class _FailingStorage:
    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        raise RedisError("down")

    async def store_failed_delivery(self, **kwargs) -> str:
        raise RedisError("down")


def test_fallback_storage_uses_memory_when_primary_fails() -> None:
    memory = MemoryStorage(idempotency_ttl=3600)
    storage = FallbackStorage(primary=_FailingStorage(), fallback=memory)

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
