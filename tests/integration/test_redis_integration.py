import uuid

import pytest

from app.infra.storage import RedisStorage

pytestmark = pytest.mark.integration


async def _get_redis_client():
    pytest.importorskip("redis")
    from redis.asyncio import Redis

    redis = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    try:
        await redis.ping()
    except Exception as exc:  # pragma: no cover - env dependent
        await redis.aclose()
        pytest.skip(f"Redis not available: {exc}")
    return redis


@pytest.mark.asyncio
async def test_redis_storage_duplicate_detection_round_trip() -> None:
    redis = await _get_redis_client()
    prefix = f"test:webhook-bridge:{uuid.uuid4().hex}"
    storage = RedisStorage(redis, key_prefix=prefix, idempotency_ttl=60)

    try:
        assert await storage.is_duplicate_delivery("d1") is False
        assert await storage.is_duplicate_delivery("d1") is True
    finally:
        keys = await redis.keys(f"{prefix}:*")
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


@pytest.mark.asyncio
async def test_redis_storage_failed_delivery_persistence() -> None:
    redis = await _get_redis_client()
    prefix = f"test:webhook-bridge:{uuid.uuid4().hex}"
    storage = RedisStorage(redis, key_prefix=prefix, idempotency_ttl=60)

    try:
        failed_id = await storage.store_failed_delivery(
            source="github",
            event_type="push",
            payload={"repository": {"full_name": "org/repo"}},
            headers={"x-github-event": "push"},
            error="send failed",
            delivery_id="abc-123",
        )

        item = await storage.get_failed_delivery(failed_id)
        assert item is not None
        assert item["source"] == "github"
        assert item["status"] == "failed"

        await storage.update_failed_delivery_status(failed_id, "retried")
        updated = await storage.get_failed_delivery(failed_id)
        assert updated is not None
        assert updated["status"] == "retried"

        rows, total = await storage.list_failed_deliveries(source="github", status="retried")
        assert total == 1
        assert rows[0]["id"] == failed_id
    finally:
        keys = await redis.keys(f"{prefix}:*")
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
