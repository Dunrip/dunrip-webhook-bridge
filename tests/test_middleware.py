from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware import MemoryRateLimitBackend, RateLimitMiddleware


def _build_client(ip_limit: int = 10, token_limit: int = 30, admin_limit: int = 20) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        backend=MemoryRateLimitBackend(),
        ip_limit_per_minute=ip_limit,
        token_limit_per_minute=token_limit,
        admin_limit_per_minute=admin_limit,
    )

    @app.post("/webhook/github")
    async def github() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/generic")
    async def generic() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/deliveries")
    async def deliveries() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_rate_limit_per_ip_for_github() -> None:
    client = _build_client(ip_limit=1)

    first = client.post("/webhook/github")
    second = client.post("/webhook/github")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get("Retry-After") is not None


def test_rate_limit_per_token_for_generic() -> None:
    client = _build_client(ip_limit=100, token_limit=1)

    first = client.post("/webhook/generic", headers={"X-Webhook-Token": "token-a"})
    second = client.post("/webhook/generic", headers={"X-Webhook-Token": "token-a"})
    third = client.post("/webhook/generic", headers={"X-Webhook-Token": "token-b"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert third.status_code == 200


def test_rate_limit_admin_endpoint() -> None:
    client = _build_client(admin_limit=1)

    first = client.get("/deliveries")
    second = client.get("/deliveries")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["message"] == "Admin rate limit exceeded"
