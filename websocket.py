"""WebSocket endpoint for real-time event log streaming.

Clients connect to ``/stream/logs`` and optionally provide query-parameter
filters (``event_type``, ``status``, ``repo``).  Events are broadcast as
JSON frames to every matching connected client.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from security import validate_admin_api_key_headers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])


@dataclass
class _Client:
    """A connected WebSocket client with optional filters."""

    ws: WebSocket
    event_type: str | None = None
    status: str | None = None
    repo: str | None = None


class EventBroadcaster:
    """Manages connected WebSocket clients and broadcasts events."""

    def __init__(self) -> None:
        self._clients: list[_Client] = []
        self._lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # type: ignore[assignment]
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, client: _Client) -> None:
        async with self._lock:
            self._clients.append(client)
        logger.info("WebSocket client connected (total=%d)", len(self._clients))

    async def disconnect(self, client: _Client) -> None:
        async with self._lock:
            try:
                self._clients.remove(client)
            except ValueError:
                pass
        logger.info("WebSocket client disconnected (total=%d)", len(self._clients))

    def _matches(self, client: _Client, event: dict[str, Any]) -> bool:
        if client.event_type and event.get("event_type") != client.event_type:
            return False
        if client.status and event.get("status") != client.status:
            return False
        if client.repo:
            repo = ""
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                repository = payload.get("repository")
                if isinstance(repository, dict):
                    repo = repository.get("full_name", "")
            if client.repo != repo:
                return False
        return True

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send *event* to all connected clients whose filters match."""
        data = json.dumps(event)
        async with self._lock:
            clients = list(self._clients)

        disconnected: list[_Client] = []
        for client in clients:
            if not self._matches(client, event):
                continue
            try:
                await client.ws.send_text(data)
            except Exception:
                disconnected.append(client)

        for client in disconnected:
            await self.disconnect(client)


# Module-level broadcaster singleton
broadcaster = EventBroadcaster()


@router.websocket("/stream/logs")
async def stream_logs(
    ws: WebSocket,
    event_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    repo: str | None = Query(default=None),
) -> None:
    """WebSocket endpoint for live event streaming with optional filters."""
    if not validate_admin_api_key_headers(ws.headers):
        logger.warning("WebSocket stream auth failed")
        await ws.close(code=1008)
        return

    await ws.accept()
    client = _Client(ws=ws, event_type=event_type, status=status, repo=repo)
    await broadcaster.connect(client)
    try:
        # Keep connection alive - wait for client disconnect
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(client)
