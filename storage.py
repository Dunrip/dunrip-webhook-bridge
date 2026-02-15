import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

try:
    from redis import RedisError
    from redis.asyncio import Redis
except ModuleNotFoundError:  # pragma: no cover - exercised in no-network envs
    Redis = None

    class RedisError(Exception):
        pass

from config import settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        ...

    async def store_failed_delivery(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        error: str | None = None,
        delivery_id: str | None = None,
    ) -> str:
        ...

    async def list_failed_deliveries(
        self,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ...

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        ...

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        ...


class MemoryStorage:
    def __init__(self, idempotency_ttl: int, failed_delivery_ttl: int = 604800) -> None:
        self._idempotency_ttl = idempotency_ttl
        self._failed_delivery_ttl = failed_delivery_ttl
        self._idempotency_store: dict[str, float] = {}
        self.failed_deliveries: dict[str, dict[str, Any]] = {}

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        if not delivery_id:
            return False

        now = time.time()
        cutoff = now - self._idempotency_ttl
        if len(self._idempotency_store) > 1000 and hash(delivery_id) % 10 == 0:
            self._idempotency_store = {
                key: ts for key, ts in self._idempotency_store.items() if ts >= cutoff
            }

        existing = self._idempotency_store.get(delivery_id)
        if existing and now - existing < self._idempotency_ttl:
            return True

        self._idempotency_store[delivery_id] = now
        return False

    async def store_failed_delivery(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        error: str | None = None,
        delivery_id: str | None = None,
    ) -> str:
        now = time.time()
        cutoff = now - self._failed_delivery_ttl
        if len(self.failed_deliveries) > 1000:
            self.failed_deliveries = {
                key: record
                for key, record in self.failed_deliveries.items()
                if record["created_at_unix"] >= cutoff
            }

        failed_id = str(uuid.uuid4())
        self.failed_deliveries[failed_id] = {
            "id": failed_id,
            "source": source,
            "event_type": event_type,
            "payload": payload,
            "headers": dict(headers or {}),
            "error": error,
            "delivery_id": delivery_id,
            "status": "failed",
            "created_at_unix": now,
        }
        return failed_id

    async def list_failed_deliveries(
        self,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        records = list(self.failed_deliveries.values())
        if source:
            records = [r for r in records if r["source"] == source]
        if status:
            records = [r for r in records if r["status"] == status]
        records.sort(key=lambda r: r["created_at_unix"], reverse=True)
        total = len(records)
        return records[offset : offset + limit], total

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        return self.failed_deliveries.get(failed_id)

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        record = self.failed_deliveries.get(failed_id)
        if record:
            record["status"] = status


class RedisStorage:
    def __init__(
        self,
        redis_client: Any,
        key_prefix: str,
        idempotency_ttl: int,
    ) -> None:
        if Redis is None:
            raise RedisError("redis package is not installed")
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._idempotency_ttl = idempotency_ttl

    def _delivery_key(self, delivery_id: str) -> str:
        return f"{self._key_prefix}:delivery:{delivery_id}"

    def _failed_key(self, failed_id: str) -> str:
        return f"{self._key_prefix}:failed:{failed_id}"

    def _failed_index_key(self) -> str:
        return f"{self._key_prefix}:failed:index"

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        if not delivery_id:
            return False
        was_set = await self._redis.set(
            self._delivery_key(delivery_id),
            "1",
            nx=True,
            ex=self._idempotency_ttl,
        )
        return was_set is None

    async def store_failed_delivery(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        error: str | None = None,
        delivery_id: str | None = None,
    ) -> str:
        failed_id = str(uuid.uuid4())
        record = {
            "id": failed_id,
            "source": source,
            "event_type": event_type,
            "payload": payload,
            "headers": dict(headers or {}),
            "error": error,
            "delivery_id": delivery_id,
            "status": "failed",
            "created_at_unix": time.time(),
        }
        await self._redis.set(self._failed_key(failed_id), json.dumps(record))
        await self._redis.lpush(self._failed_index_key(), failed_id)
        return failed_id

    async def list_failed_deliveries(
        self,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        failed_ids = await self._redis.lrange(self._failed_index_key(), 0, -1)
        if not failed_ids:
            return [], 0

        raw_records = await self._redis.mget([self._failed_key(failed_id) for failed_id in failed_ids])

        records: list[dict[str, Any]] = []
        for raw in raw_records:
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if source and record.get("source") != source:
                continue
            if status and record.get("status") != status:
                continue
            records.append(record)

        total = len(records)
        return records[offset : offset + limit], total

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._failed_key(failed_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        record = await self.get_failed_delivery(failed_id)
        if not record:
            return
        record["status"] = status
        await self._redis.set(self._failed_key(failed_id), json.dumps(record))


class FallbackStorage:
    def __init__(self, primary: Storage, fallback: Storage) -> None:
        self._primary = primary
        self._fallback = fallback
        self._warned = False

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        try:
            return await self._primary.is_duplicate_delivery(delivery_id)
        except RedisError as exc:
            if not self._warned:
                logger.warning(
                    "Primary Redis storage unavailable, falling back to memory: %s",
                    exc,
                )
                self._warned = True
            return await self._fallback.is_duplicate_delivery(delivery_id)

    async def store_failed_delivery(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        error: str | None = None,
        delivery_id: str | None = None,
    ) -> str:
        try:
            return await self._primary.store_failed_delivery(
                source=source,
                event_type=event_type,
                payload=payload,
                headers=headers,
                error=error,
                delivery_id=delivery_id,
            )
        except RedisError as exc:
            if not self._warned:
                logger.warning(
                    "Primary Redis storage unavailable, falling back to memory: %s",
                    exc,
                )
                self._warned = True
            return await self._fallback.store_failed_delivery(
                source=source,
                event_type=event_type,
                payload=payload,
                headers=headers,
                error=error,
                delivery_id=delivery_id,
            )

    async def list_failed_deliveries(
        self,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        try:
            return await self._primary.list_failed_deliveries(source, status, limit, offset)
        except RedisError:
            return await self._fallback.list_failed_deliveries(source, status, limit, offset)

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        try:
            return await self._primary.get_failed_delivery(failed_id)
        except RedisError:
            return await self._fallback.get_failed_delivery(failed_id)

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        try:
            await self._primary.update_failed_delivery_status(failed_id, status)
        except RedisError:
            await self._fallback.update_failed_delivery_status(failed_id, status)


def create_storage_backend(redis_client: Any | None = None) -> Storage:
    memory_backend = MemoryStorage(
        idempotency_ttl=settings.idempotency_ttl,
        failed_delivery_ttl=settings.failed_delivery_ttl,
    )
    if settings.storage_backend.lower() == "redis":
        try:
            if redis_client is None:
                raise RedisError("Redis client not initialized")
            return FallbackStorage(
                primary=RedisStorage(
                    redis_client=redis_client,
                    key_prefix=settings.redis_key_prefix,
                    idempotency_ttl=settings.idempotency_ttl,
                ),
                fallback=memory_backend,
            )
        except RedisError as exc:
            logger.warning(
                "Redis storage requested but unavailable, using memory backend: %s",
                exc,
            )
            return memory_backend
    return memory_backend
