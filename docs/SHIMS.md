# Root Shim Modules Removed

Status: ✅ Migration complete.

This repository no longer keeps compatibility shim modules in the repository root.

## What changed

The following former root-level shim modules were removed:

- `main.py`
- `config.py`
- `security.py`
- `errors.py`
- `exceptions.py`
- `replay.py`
- `sandbox.py`
- `websocket.py`
- `github_app.py`
- `tg_client.py`
- `routing.py`
- `formatters.py`
- `templates.py`
- `storage.py`
- `middleware.py`
- `circuit_breaker.py`
- `models.py`
- `observability.py`

## Canonical imports

Use `app.*` paths everywhere:

- `app.main`
- `app.core.config`
- `app.core.security`
- `app.core.errors`
- `app.core.exceptions`
- `app.api.github_app`
- `app.api.replay`
- `app.api.sandbox`
- `app.api.websocket`
- `app.services.tg_client`
- `app.services.routing`
- `app.services.formatters`
- `app.services.templates`
- `app.infra.storage`
- `app.infra.middleware`
- `app.infra.circuit_breaker`
- `app.models.models`
- `app.observability.observability`

## Runtime entrypoints

- Vercel entrypoint (`api/index.py`): `from app.main import app`
- Uvicorn examples / container command: `app.main:app`
