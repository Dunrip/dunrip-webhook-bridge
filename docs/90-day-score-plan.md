# 90-Day Score Execution Plan

Execution tracker for issues #28-#32.

## Sprint 1 (this PR)

### #28 CI reliability gate + failure triage policy

- [x] Hardened CI workflow (`.github/workflows/ci.yml`): concurrency cancel, timeout, pip cache, non-blocking reporting/comment steps
- [x] Restricted-context-safe bot/comment behavior (PR comment step only on non-fork PRs + `continue-on-error`)
- [x] Added triage playbook: [`docs/ops/ci-failure-triage.md`](docs/ops/ci-failure-triage.md)
- [x] Linked triage guidance from contributor/user docs (`README.md`, `CONTRIBUTING.md`)

### #29 Security remediation SLA + release hardening

- [x] Added severity-based remediation SLA to [`SECURITY.md`](../SECURITY.md)
- [x] Extended release checklist with mandatory security checks + explicit signoff (`docs/release-checklist.md`)
- [x] Enforced release security gates in workflow (`.github/workflows/release.yml`)
- [x] Added explicit scan result summaries in security workflows (`security-deps.yml`, `security-secrets.yml`)

### #31 Reliability benchmark trend + regression guardrail

- [x] Added benchmark script with baseline write/read + compare/fail mode (`scripts/benchmark_local.py`)
- [x] Added Makefile targets (`benchmark`, `benchmark-baseline`, `benchmark-compare`)
- [x] Added benchmark docs for local/CI usage (`docs/monitoring/reliability-benchmark.md`)
- [x] Added tests for benchmark compare guardrail (`tests/test_benchmark_local.py`)

## Sprint 2 (next)

### #30 Operational runbooks & alerting hardening

- [ ] Expand incident runbooks for top failure modes and operator drills
- [ ] Add alert ownership/escalation mapping and SLO burn-rate tuning

### #32 Release governance + post-release verification automation

- [ ] Automate release signoff evidence capture in GitHub artifacts
- [ ] Add post-release validation workflow automation (health/metrics smoke gate)
