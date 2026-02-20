# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README polish: badges, 3-command quickstart callout, and sample Telegram output section.
- `example.env.minimal` for required-only startup configuration.
- Startup mode summary logs (auth mode, storage backend, runtime indicators).
- Monitoring starter docs and dashboard artifacts:
  - `docs/monitoring/alerts.md`
  - `docs/monitoring/grafana-dashboard.json`
- Redis backup/restore operations guide: `docs/ops/redis-backup.md`.
- Compact API reference and routing use-case documentation.
- Release automation helper script and release template (see upcoming release section updates).

### Changed
- Improved admin auth env conflict warnings with explicit fix paths.
- Clarified `POST /deliveries/replay-all` contract as asynchronous acceptance (`status: accepted`, `queued`) with background processing.
- GHCR Trivy gate now distinguishes non-release (`main`) non-blocking scans vs release-tag blocking scans, with CI step summaries.
- GHCR image build now refreshes pip/setuptools/wheel toolchain in builder/runtime stages to reduce known Trivy CVEs.
- Trivy GHCR workflow now uses vulnerability scanner mode (`scanners: vuln`) to avoid secret-pattern false positives from package metadata.
- Discord/Slack destinations now include bounded retry handling (429 + Retry-After + transient network/server failures) and richer destination error classification metadata.
- Destination health now reports readiness details (enabled/configured/ready/reason) in `/health/deep` routing snapshot.
- Route loading now warns on unready destinations and supports strict startup failure mode via `ROUTES_STRICT_VALIDATION=true`.
- Added webhook URL validation for `DISCORD_WEBHOOK_URL` and `SLACK_WEBHOOK_URL`.
- Added destination-level delivery metrics for attempts/failures/retries/rate-limit events/latency.

### Docs
- Added release checklist smoke verification expansion and operational guidance.
- Added replay operations guide with replay-all semantics and verification workflow: `docs/ops/replay-operations.md`.
- Added Trivy GHCR gate policy and suppression process documentation: `docs/ops/trivy-ghcr-policy.md`.
- Expanded deployment UX docs with prefilled Vercel env link and explicit Redis-mode prompt handling for Render/Vercel guides.
