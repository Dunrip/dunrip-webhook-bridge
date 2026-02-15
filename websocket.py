"""WebSocket endpoint for real-time event log streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from config import settings
from observability import audit_log, fingerprint_api_key
from security import validate_admin_api_key_headers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])


@dataclass
class _Client:
    ws: WebSocket
    event_type: str | None = None
    status: str | None = None
    repo: str | None = None
    ip: str = "unknown"


class EventBroadcaster:
    def __init__(self) -> None:
        self._clients: list[_Client] = []
        self._lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # type: ignore[assignment]
        self._lock = asyncio.Lock()
        self._connect_attempts: dict[str, tuple[int, float]] = {}
        self._connections_per_ip: dict[str, int] = defaultdict(int)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def allow_connect(self, ip: str) -> tuple[bool, str]:
        now = time.time()
        count, expires = self._connect_attempts.get(ip, (0, now + 60))
        if now >= expires:
            count = 0
            expires = now + 60
        count += 1
        self._connect_attempts[ip] = (count, expires)

        if settings.ws_connects_per_minute > 0 and count > settings.ws_connects_per_minute:
            return False, "connect_rate_limited"

        if settings.ws_max_connections_per_ip > 0 and self._connections_per_ip[ip] >= settings.ws_max_connections_per_ip:
            return False, "max_connections_per_ip_exceeded"

        return True, "ok"

    async def connect(self, client: _Client) -> None:
        async with self._lock:
            self._clients.append(client)
            self._connections_per_ip[client.ip] += 1
        logger.info("WebSocket client connected (total=%d)", len(self._clients))

    async def disconnect(self, client: _Client) -> None:
        async with self._lock:
            try:
                self._clients.remove(client)
                self._connections_per_ip[client.ip] = max(0, self._connections_per_ip[client.ip] - 1)
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


broadcaster = EventBroadcaster()


@router.websocket("/stream/logs")
async def stream_logs(
    ws: WebSocket,
    event_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    repo: str | None = Query(default=None),
) -> None:
    client_ip = ws.client.host if ws.client else "unknown"
    provided_key = ws.headers.get("x-api-key")
    actor = fingerprint_api_key(provided_key)

    auth_ok = validate_admin_api_key_headers(ws.headers)
    if not auth_ok:
        audit_log(
            logger,
            action="WS /stream/logs",
            request_id=ws.headers.get("x-request-id", "-"),
            client_ip=client_ip,
            auth_result="deny",
            delivery_id=None,
            status="auth_failed",
            actor=actor if provided_key else "api-key",
        )
        logger.warning("WebSocket stream auth failed")
        await ws.close(code=1008)
        return

    allowed, reason = await broadcaster.allow_connect(client_ip)
    if not allowed:
        audit_log(
            logger,
            action="WS /stream/logs",
            request_id=ws.headers.get("x-request-id", "-"),
            client_ip=client_ip,
            auth_result="allow",
            delivery_id=None,
            status=reason,
            actor=actor,
        )
        await ws.close(code=1013)
        return

    await ws.accept()
    audit_log(
        logger,
        action="WS /stream/logs",
        request_id=ws.headers.get("x-request-id", "-"),
        client_ip=client_ip,
        auth_result="allow",
        delivery_id=None,
        status="connected",
        actor=actor,
    )
    client = _Client(ws=ws, event_type=event_type, status=status, repo=repo, ip=client_ip)
    await broadcaster.connect(client)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(client)
