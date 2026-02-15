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


class RedisStorage:
    def __init__(
        self,
        redis_url: str,
        key_prefix: str,
        idempotency_ttl: int,
    ) -> None:
        if Redis is None:
            raise RedisError("redis package is not installed")
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix
        self._idempotency_ttl = idempotency_ttl

    def _delivery_key(self, delivery_id: str) -> str:
        return f"{self._key_prefix}:delivery:{delivery_id}"

    def _failed_key(self, failed_id: str) -> str:
        return f"{self._key_prefix}:failed:{failed_id}"

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
        await self._redis.lpush(f"{self._key_prefix}:failed:index", failed_id)
        return failed_id


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


def create_storage_backend() -> Storage:
    memory_backend = MemoryStorage(
        idempotency_ttl=settings.idempotency_ttl,
        failed_delivery_ttl=settings.failed_delivery_ttl,
    )
    if settings.storage_backend.lower() == "redis":
        try:
            return FallbackStorage(
                primary=RedisStorage(
                    redis_url=settings.redis_url,
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
