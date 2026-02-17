"""Storage backends for idempotency and failed-delivery persistence.

Provides an in-memory backend, Redis backend, and fallback composition that
degrades gracefully to memory when Redis is unavailable.
"""

from __future__ import annotations

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
        """Fallback Redis error type when redis package is unavailable."""


from app.core.config import settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    """Protocol for idempotency and failed-delivery storage implementations."""

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        """Return True when a delivery ID was already processed recently."""
        ...

    async def is_duplicate_replay_operation(self, operation_key: str, ttl_seconds: int) -> bool:
        """Return True when replay operation key was already seen inside ttl."""
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
        """Persist a failed delivery record and return its generated ID."""
        ...

    async def list_failed_deliveries(
        self,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List failed deliveries with optional filtering and pagination."""
        ...

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        """Fetch a failed delivery by ID."""
        ...

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        """Update status for a failed delivery record."""
        ...

    async def update_failed_delivery(self, failed_id: str, updates: Mapping[str, Any]) -> None:
        """Apply partial field updates to a failed delivery record."""
        ...

    async def upsert_delivery_ledger(
        self,
        provider: str,
        inbound_delivery_id: str,
        payload_hash: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create or update delivery ledger metadata and append transition."""
        ...

    async def get_delivery_ledger(self, provider: str, inbound_delivery_id: str) -> dict[str, Any] | None:
        """Get delivery ledger metadata by provider and inbound delivery id."""
        ...


class MemoryStorage:
    """In-memory storage backend for local/dev/test usage."""

    def __init__(self, idempotency_ttl: int, failed_delivery_ttl: int = 604800) -> None:
        """Initialize in-memory storage.

        Args:
            idempotency_ttl: Number of seconds to remember delivery IDs.
            failed_delivery_ttl: Number of seconds to keep failed delivery records.
        """
        self._idempotency_ttl = idempotency_ttl
        self._failed_delivery_ttl = failed_delivery_ttl
        self._idempotency_store: dict[str, float] = {}
        self._replay_operation_store: dict[str, float] = {}
        self.failed_deliveries: dict[str, dict[str, Any]] = {}
        self.delivery_ledger: dict[str, dict[str, Any]] = {}

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        """Check and record delivery IDs for idempotency."""
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

    async def is_duplicate_replay_operation(self, operation_key: str, ttl_seconds: int) -> bool:
        """Check and record replay operation idempotency keys."""
        now = time.time()
        cutoff = now - ttl_seconds
        if len(self._replay_operation_store) > 1000:
            self._replay_operation_store = {
                key: ts for key, ts in self._replay_operation_store.items() if ts >= cutoff
            }

        existing = self._replay_operation_store.get(operation_key)
        if existing and now - existing < ttl_seconds:
            return True

        self._replay_operation_store[operation_key] = now
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
        """Store a failed delivery record in memory."""
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
            "replay_attempts": 0,
            "last_replay_at": None,
            "last_replay_status": None,
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
        """List failed deliveries with filtering and pagination."""
        records = list(self.failed_deliveries.values())
        if source:
            records = [r for r in records if r["source"] == source]
        if status:
            records = [r for r in records if r["status"] == status]
        records.sort(key=lambda r: r["created_at_unix"], reverse=True)
        total = len(records)
        return records[offset : offset + limit], total

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        """Get a failed delivery by ID from memory."""
        return self.failed_deliveries.get(failed_id)

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        """Update status of an in-memory failed delivery record."""
        record = self.failed_deliveries.get(failed_id)
        if record:
            record["status"] = status

    async def update_failed_delivery(self, failed_id: str, updates: Mapping[str, Any]) -> None:
        """Apply partial updates to an in-memory failed delivery record."""
        record = self.failed_deliveries.get(failed_id)
        if record:
            record.update(dict(updates))

    async def upsert_delivery_ledger(
        self,
        provider: str,
        inbound_delivery_id: str,
        payload_hash: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        key = f"{provider}:{inbound_delivery_id}"
        now = time.time()
        existing = self.delivery_ledger.get(key)
        if not existing:
            existing = {
                "provider": provider,
                "inbound_delivery_id": inbound_delivery_id,
                "payload_hash": payload_hash,
                "first_seen": now,
                "status": status,
                "status_transitions": [],
            }
            self.delivery_ledger[key] = existing
        existing["status"] = status
        if reason:
            existing["reason"] = reason
        existing["status_transitions"].append({"status": status, "at": now, "reason": reason})
        return existing

    async def get_delivery_ledger(self, provider: str, inbound_delivery_id: str) -> dict[str, Any] | None:
        return self.delivery_ledger.get(f"{provider}:{inbound_delivery_id}")


class RedisStorage:
    """Redis-backed storage backend for production persistence."""

    def __init__(
        self,
        redis_client: Any,
        key_prefix: str,
        idempotency_ttl: int,
    ) -> None:
        """Initialize Redis storage.

        Args:
            redis_client: Async Redis client instance.
            key_prefix: Namespace prefix for all Redis keys.
            idempotency_ttl: TTL in seconds for delivery-id idempotency keys.

        Raises:
            RedisError: If redis package is unavailable.
        """
        if Redis is None:
            raise RedisError("redis package is not installed")
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._idempotency_ttl = idempotency_ttl

    def _delivery_key(self, delivery_id: str) -> str:
        """Build Redis key for idempotency tracking."""
        return f"{self._key_prefix}:delivery:{delivery_id}"

    def _failed_key(self, failed_id: str) -> str:
        """Build Redis key for an individual failed delivery record."""
        return f"{self._key_prefix}:failed:{failed_id}"

    def _failed_index_key(self) -> str:
        """Build Redis list key storing failed-delivery IDs."""
        return f"{self._key_prefix}:failed:index"

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        """Atomically check/set idempotency key in Redis."""
        if not delivery_id:
            return False
        was_set = await self._redis.set(
            self._delivery_key(delivery_id),
            "1",
            nx=True,
            ex=self._idempotency_ttl,
        )
        return was_set is None

    async def is_duplicate_replay_operation(self, operation_key: str, ttl_seconds: int) -> bool:
        """Atomically check/set replay operation idempotency key in Redis."""
        was_set = await self._redis.set(
            f"{self._key_prefix}:replay-op:{operation_key}",
            "1",
            nx=True,
            ex=ttl_seconds,
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
        """Store failed delivery record and index it in Redis."""
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
            "replay_attempts": 0,
            "last_replay_at": None,
            "last_replay_status": None,
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
        """List failed deliveries stored in Redis."""
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
        """Fetch failed delivery record from Redis."""
        raw = await self._redis.get(self._failed_key(failed_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        """Update failed delivery status in Redis."""
        record = await self.get_failed_delivery(failed_id)
        if not record:
            return
        record["status"] = status
        await self._redis.set(self._failed_key(failed_id), json.dumps(record))

    async def update_failed_delivery(self, failed_id: str, updates: Mapping[str, Any]) -> None:
        """Apply partial updates to a failed delivery record in Redis."""
        record = await self.get_failed_delivery(failed_id)
        if not record:
            return
        record.update(dict(updates))
        await self._redis.set(self._failed_key(failed_id), json.dumps(record))

    def _ledger_key(self, provider: str, inbound_delivery_id: str) -> str:
        return f"{self._key_prefix}:ledger:{provider}:{inbound_delivery_id}"

    async def upsert_delivery_ledger(
        self,
        provider: str,
        inbound_delivery_id: str,
        payload_hash: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        key = self._ledger_key(provider, inbound_delivery_id)
        existing_raw = await self._redis.get(key)
        now = time.time()
        if existing_raw:
            existing = json.loads(existing_raw)
        else:
            existing = {
                "provider": provider,
                "inbound_delivery_id": inbound_delivery_id,
                "payload_hash": payload_hash,
                "first_seen": now,
                "status_transitions": [],
            }
        existing["status"] = status
        existing["payload_hash"] = payload_hash
        if reason:
            existing["reason"] = reason
        existing.setdefault("status_transitions", []).append({"status": status, "at": now, "reason": reason})
        await self._redis.set(key, json.dumps(existing))
        return existing

    async def get_delivery_ledger(self, provider: str, inbound_delivery_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._ledger_key(provider, inbound_delivery_id))
        if not raw:
            return None
        return json.loads(raw)


class FallbackStorage:
    """Storage wrapper that falls back to memory when primary backend fails."""

    def __init__(self, primary: Storage, fallback: Storage) -> None:
        self._primary = primary
        self._fallback = fallback
        self._warned = False

    async def is_duplicate_delivery(self, delivery_id: str | None) -> bool:
        """Check idempotency using primary storage, then fallback if needed."""
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

    async def is_duplicate_replay_operation(self, operation_key: str, ttl_seconds: int) -> bool:
        """Check replay operation idempotency with fallback behavior."""
        try:
            return await self._primary.is_duplicate_replay_operation(operation_key, ttl_seconds)
        except RedisError as exc:
            if not self._warned:
                logger.warning(
                    "Primary Redis storage unavailable, falling back to memory: %s",
                    exc,
                )
                self._warned = True
            return await self._fallback.is_duplicate_replay_operation(operation_key, ttl_seconds)

    async def store_failed_delivery(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        error: str | None = None,
        delivery_id: str | None = None,
    ) -> str:
        """Store failed delivery on primary backend, or fallback on Redis errors."""
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
        """List failed deliveries with fallback behavior."""
        try:
            return await self._primary.list_failed_deliveries(source, status, limit, offset)
        except RedisError:
            return await self._fallback.list_failed_deliveries(source, status, limit, offset)

    async def get_failed_delivery(self, failed_id: str) -> dict[str, Any] | None:
        """Get failed delivery by ID with fallback behavior."""
        try:
            return await self._primary.get_failed_delivery(failed_id)
        except RedisError:
            return await self._fallback.get_failed_delivery(failed_id)

    async def update_failed_delivery_status(self, failed_id: str, status: str) -> None:
        """Update failed delivery status with fallback behavior."""
        try:
            await self._primary.update_failed_delivery_status(failed_id, status)
        except RedisError:
            await self._fallback.update_failed_delivery_status(failed_id, status)

    async def update_failed_delivery(self, failed_id: str, updates: Mapping[str, Any]) -> None:
        """Apply partial updates with fallback behavior."""
        try:
            await self._primary.update_failed_delivery(failed_id, updates)
        except RedisError:
            await self._fallback.update_failed_delivery(failed_id, updates)

    async def upsert_delivery_ledger(
        self,
        provider: str,
        inbound_delivery_id: str,
        payload_hash: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._primary.upsert_delivery_ledger(provider, inbound_delivery_id, payload_hash, status, reason)
        except RedisError:
            return await self._fallback.upsert_delivery_ledger(provider, inbound_delivery_id, payload_hash, status, reason)

    async def get_delivery_ledger(self, provider: str, inbound_delivery_id: str) -> dict[str, Any] | None:
        try:
            return await self._primary.get_delivery_ledger(provider, inbound_delivery_id)
        except RedisError:
            return await self._fallback.get_delivery_ledger(provider, inbound_delivery_id)


def create_storage_backend(redis_client: Any | None = None) -> Storage:
    """Create configured storage backend.

    Args:
        redis_client: Optional initialized async Redis client.

    Returns:
        Storage implementation based on configuration and runtime availability.
    """
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
