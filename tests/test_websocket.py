"""Tests for WebSocket streaming."""

import pytest
from starlette.websockets import WebSocketDisconnect

import main
from websocket import EventBroadcaster, _Client


class FakeWebSocket:
    """Minimal mock of a FastAPI WebSocket."""

    def __init__(self):
        self.sent: list[str] = []
        self.should_fail = False

    async def send_text(self, data: str) -> None:
        if self.should_fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


# ---------------------------------------------------------------------------
# EventBroadcaster
# ---------------------------------------------------------------------------

class TestEventBroadcaster:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        b = EventBroadcaster()
        ws = FakeWebSocket()
        client = _Client(ws=ws)
        await b.connect(client)
        assert b.client_count == 1
        await b.disconnect(client)
        assert b.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self):
        b = EventBroadcaster()
        ws = FakeWebSocket()
        client = _Client(ws=ws)
        await b.disconnect(client)  # not connected, should not error
        assert b.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self):
        b = EventBroadcaster()
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        c1 = _Client(ws=ws1)
        c2 = _Client(ws=ws2)
        await b.connect(c1)
        await b.connect(c2)

        await b.broadcast({"event_type": "push", "status": "success", "payload": {}})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1

    @pytest.mark.asyncio
    async def test_broadcast_filters_event_type(self):
        b = EventBroadcaster()
        ws_push = FakeWebSocket()
        ws_all = FakeWebSocket()
        c_push = _Client(ws=ws_push, event_type="push")
        c_all = _Client(ws=ws_all)
        await b.connect(c_push)
        await b.connect(c_all)

        await b.broadcast({"event_type": "issues", "status": "success", "payload": {}})
        assert len(ws_push.sent) == 0  # filtered out
        assert len(ws_all.sent) == 1   # no filter

    @pytest.mark.asyncio
    async def test_broadcast_filters_status(self):
        b = EventBroadcaster()
        ws = FakeWebSocket()
        c = _Client(ws=ws, status="failed")
        await b.connect(c)

        await b.broadcast({"event_type": "push", "status": "success", "payload": {}})
        assert len(ws.sent) == 0

        await b.broadcast({"event_type": "push", "status": "failed", "payload": {}})
        assert len(ws.sent) == 1

    @pytest.mark.asyncio
    async def test_broadcast_filters_repo(self):
        b = EventBroadcaster()
        ws = FakeWebSocket()
        c = _Client(ws=ws, repo="a/b")
        await b.connect(c)

        await b.broadcast({
            "event_type": "push", "status": "success",
            "payload": {"repository": {"full_name": "a/b"}},
        })
        assert len(ws.sent) == 1

        await b.broadcast({
            "event_type": "push", "status": "success",
            "payload": {"repository": {"full_name": "x/y"}},
        })
        assert len(ws.sent) == 1  # still 1, second was filtered

    @pytest.mark.asyncio
    async def test_broadcast_disconnects_broken_clients(self):
        b = EventBroadcaster()
        ws_ok = FakeWebSocket()
        ws_bad = FakeWebSocket()
        ws_bad.should_fail = True
        c_ok = _Client(ws=ws_ok)
        c_bad = _Client(ws=ws_bad)
        await b.connect(c_ok)
        await b.connect(c_bad)
        assert b.client_count == 2

        await b.broadcast({"event_type": "push", "status": "success", "payload": {}})
        assert len(ws_ok.sent) == 1
        assert b.client_count == 1  # bad client removed

    @pytest.mark.asyncio
    async def test_broadcast_combined_filters(self):
        b = EventBroadcaster()
        ws = FakeWebSocket()
        c = _Client(ws=ws, event_type="push", repo="a/b")
        await b.connect(c)

        # Matches both
        await b.broadcast({
            "event_type": "push", "status": "success",
            "payload": {"repository": {"full_name": "a/b"}},
        })
        assert len(ws.sent) == 1

        # Wrong event type
        await b.broadcast({
            "event_type": "issues", "status": "success",
            "payload": {"repository": {"full_name": "a/b"}},
        })
        assert len(ws.sent) == 1  # not incremented


def _app_client(monkeypatch):
    monkeypatch.setattr(main.settings, "github_webhook_secret", "gh-secret")
    monkeypatch.setattr(main.settings, "generic_webhook_token", "generic-token")
    monkeypatch.setattr(main.settings, "admin_api_key", "admin-test-key")
    monkeypatch.setattr(main.settings, "storage_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(main.settings, "rate_limit_admin_per_minute", 1000)
    app = main.create_app()
    from websocket import broadcaster
    broadcaster._connect_attempts.clear()
    broadcaster._connections_per_ip.clear()
    broadcaster._clients.clear()
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_stream_logs_requires_auth(monkeypatch):
    client = _app_client(monkeypatch)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/stream/logs"):
            pass


def test_stream_logs_accepts_x_api_key(monkeypatch):
    client = _app_client(monkeypatch)
    with client.websocket_connect("/stream/logs", headers={"X-API-Key": "admin-test-key"}) as ws:
        ws.close()


def test_stream_logs_rate_limit_connect_attempts(monkeypatch):
    client = _app_client(monkeypatch)
    monkeypatch.setattr(main.settings, "ws_connects_per_minute", 1)
    with client.websocket_connect("/stream/logs", headers={"X-API-Key": "admin-test-key"}) as ws:
        ws.close()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/stream/logs", headers={"X-API-Key": "admin-test-key"}):
            pass


def test_stream_logs_max_connections_per_ip(monkeypatch):
    client = _app_client(monkeypatch)
    monkeypatch.setattr(main.settings, "ws_max_connections_per_ip", 1)
    with client.websocket_connect("/stream/logs", headers={"X-API-Key": "admin-test-key"}) as ws1:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/stream/logs", headers={"X-API-Key": "admin-test-key"}):
                pass
        ws1.close()
