# Shim Migration Status

Status: ✅ **Complete** (root cleanup finished)

## Current state

- Root-level compatibility shim modules are no longer part of the active runtime path.
- Canonical app imports are under `app.*`.
- This file is retained as a top-level status pointer for anyone arriving from older docs/PRs.

## Timeline summary

- **Phase 1 (historical):** root shims introduced to ease migration into `app/` package layout.
- **Phase 2 (completed):** runtime/docs/tests switched to canonical `app.*` imports.
- **Phase 3 (completed):** root shim modules removed after verification and cleanup.

## What to use now

- App entrypoint: `app.main:app`
- Vercel entrypoint wrapper (`api/index.py`) imports from `app.main`
- Operational and migration details: see [`docs/SHIMS.md`](docs/SHIMS.md)

## Policy going forward

- Do not reintroduce root shim modules.
- New imports should always target canonical package paths under `app/`.
