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

## Release prep

- [ ] Choose next SemVer tag
- [ ] Draft release notes (what changed, migration impact, known issues)
- [ ] Verify Docker image/build health

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
