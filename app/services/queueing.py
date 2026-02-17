from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class InMemoryDeliveryQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def enqueue(self, job: dict[str, Any]) -> None:
        await self._queue.put(job)

    async def dequeue(self) -> dict[str, Any]:
        return await self._queue.get()


class RedisDeliveryQueue:
    def __init__(self, redis_client: Any, key: str) -> None:
        self._redis = redis_client
        self._key = key

    async def enqueue(self, job: dict[str, Any]) -> None:
        await self._redis.rpush(self._key, json.dumps(job))

    async def dequeue(self, timeout_seconds: int = 1) -> dict[str, Any] | None:
        item = await self._redis.blpop(self._key, timeout=timeout_seconds)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)


async def worker_loop(
    *,
    dequeue: Callable[[], Awaitable[dict[str, Any] | None]],
    handle: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        job = await dequeue()
        if not job:
            await asyncio.sleep(0.01)
            continue
        try:
            await handle(job)
        except Exception:
            logger.exception("delivery_worker_failed")
