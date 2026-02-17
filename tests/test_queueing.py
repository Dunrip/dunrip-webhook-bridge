import asyncio

import pytest

from app.services.queueing import InMemoryDeliveryQueue, worker_loop


@pytest.mark.asyncio
async def test_worker_happy_path_processes_job() -> None:
    queue = InMemoryDeliveryQueue()
    processed: list[str] = []
    stop = asyncio.Event()

    async def handle(job: dict) -> None:
        processed.append(job["id"])
        stop.set()

    async def dequeue():
        return await queue.dequeue()

    task = asyncio.create_task(worker_loop(dequeue=dequeue, handle=handle, stop_event=stop))
    await queue.enqueue({"id": "job-1"})
    await asyncio.wait_for(stop.wait(), timeout=1)
    await task

    assert processed == ["job-1"]


@pytest.mark.asyncio
async def test_worker_failure_path_continues() -> None:
    queue = InMemoryDeliveryQueue()
    seen: list[str] = []
    stop = asyncio.Event()

    async def handle(job: dict) -> None:
        seen.append(job["id"])
        if job["id"] == "bad":
            raise RuntimeError("boom")
        stop.set()

    async def dequeue():
        return await queue.dequeue()

    task = asyncio.create_task(worker_loop(dequeue=dequeue, handle=handle, stop_event=stop))
    await queue.enqueue({"id": "bad"})
    await queue.enqueue({"id": "good"})

    await asyncio.wait_for(stop.wait(), timeout=1)
    await task

    assert seen == ["bad", "good"]
