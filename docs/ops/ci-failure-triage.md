# CI Failure Triage (Fast Checklist)

Use this checklist when CI fails to cut triage time and isolate flaky failures quickly.

## 1) Classify the failure

- [ ] **Deterministic code/test failure** (same test fails repeatedly)
- [ ] **Flake/transient infra** (timeouts, network hiccup, runner instability)
- [ ] **Security gate** (`security-deps` / `security-secrets`)
- [ ] **Workflow/tooling failure** (action permission/step scripting)

## 2) Quick evidence capture

- [ ] Save failing workflow URL and job name
- [ ] Copy first failing stack trace/log line
- [ ] Note commit SHA and whether this is PR-only or also reproducible locally

## 3) Reproduce locally

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --tb=no
```

If benchmark/regression-related:

```bash
make benchmark
make benchmark-compare BASELINE=.benchmarks/local-baseline.json
```

## 4) Flake handling policy

- [ ] Re-run failed job once to confirm transient vs deterministic
- [ ] If pass-on-rerun: label as flaky and open/append a tracking issue
- [ ] If repeated failure: treat as deterministic and fix before merge
- [ ] Do **not** merge with unresolved deterministic failures

## 5) Security gate handling

- [ ] `security-deps` failed: patch/upgrade vulnerable dependency or document temporary risk acceptance in PR with owner + expiration
- [ ] `security-secrets` failed: remove/revoke leaked secret and rotate credentials before merge

## 6) Restricted-context action policy

Comment/reporting bot steps are non-blocking by design. Build health is determined by test and security gates, not PR comment permissions.
