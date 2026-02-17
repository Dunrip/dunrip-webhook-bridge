# Compatibility Shims in Repository Root

This repository still contains a set of root-level Python modules that act as **compatibility shims**.

## Why these files exist

Historically, modules were imported directly from repository root (for example `import main`, `import config`).

The codebase has now been reorganized so canonical modules live under `app/`.
To avoid breaking downstream imports immediately, root files remain as tiny proxy modules that re-export the `app.*` modules via `sys.modules` aliasing.

## Canonical import path

Use `app.*` imports for all new code.

Examples:
- `app.main`
- `app.core.config`
- `app.core.errors`
- `app.core.exceptions`
- `app.core.security`
- `app.infra.circuit_breaker`
- `app.infra.middleware`
- `app.infra.storage`
- `app.api.github_app`
- `app.api.replay`
- `app.api.sandbox`
- `app.api.websocket`
- `app.services.formatters`
- `app.services.routing`
- `app.services.templates`
- `app.services.tg_client`
- `app.models.models`
- `app.observability.observability`

## Current root shim modules

- `main.py`
- `config.py`
- `circuit_breaker.py`
- `errors.py`
- `exceptions.py`
- `formatters.py`
- `github_app.py`
- `middleware.py`
- `models.py`
- `observability.py`
- `replay.py`
- `routing.py`
- `sandbox.py`
- `security.py`
- `storage.py`
- `templates.py`
- `tg_client.py`
- `websocket.py`

## Removal plan (next major version)

1. Keep shims during current major line for backward compatibility.
2. Update internal imports, docs, and examples to `app.*` only (in progress).
3. Announce deprecation window in release notes.
4. Remove root shim modules in the next major release.
