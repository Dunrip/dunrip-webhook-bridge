# Release Checklist

Use this checklist for every release.

## Versioning policy (SemVer)

- **MAJOR**: breaking changes
- **MINOR**: backward-compatible features
- **PATCH**: backward-compatible fixes/docs/chore

Examples:
- `1.3.0` new features, no breaking changes
- `1.3.1` bugfix only
- `2.0.0` breaking config/API behavior

## Pre-release

- [ ] All CI checks passing
- [ ] Security scans passing (dependency + secrets)
- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` passes locally
- [ ] README/docs updated for user-facing changes
- [ ] `.env.example` updated for new config vars
- [ ] Migration notes added when behavior/config changed

## Security release gate (actionable)

- [ ] Confirm no hardcoded secrets in changed files (`git diff --name-only <last-tag>..HEAD` + manual scan)
- [ ] Run secrets scan locally when available (e.g. gitleaks) and verify CI secrets scan status is green
- [ ] Review dependency scan alerts for `main`; no open high/critical findings older than 7 days
- [ ] Verify webhook signature path still enforced for `/webhook/github`
- [ ] Verify admin endpoint auth mode is intentional (scoped `ADMIN_API_KEYS` or legacy `ADMIN_API_KEY`, not accidental overlap)
- [ ] If auth/security behavior changed: update `SECURITY.md` and add release note callout

## Release prep

- [ ] Choose next SemVer tag
- [ ] Draft release notes (what changed, migration impact, known issues)
- [ ] Verify Docker image/build health
- [ ] Run local reliability benchmark and capture summary in release notes:
  - `make bench-local`

## Release

- [ ] Create and push git tag (e.g., `v1.3.0`)
- [ ] Publish GitHub Release with notes
- [ ] Confirm default branch remains healthy after tag

## Post-release

- [ ] Validate smoke checks on target environment
- [ ] Validate `/health`, `/health/deep`, and `/metrics` from production ingress
- [ ] Send signed GitHub ping (`make test-github` or real webhook test repo)
- [ ] Verify at least one Telegram delivery for each critical route
- [ ] Monitor logs/alerts for first 30–60 minutes
- [ ] Confirm error-rate and latency panels stay within baseline in Grafana
- [ ] Open follow-up issues for deferred items
