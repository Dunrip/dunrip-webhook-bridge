# 90-Day Repository Score Improvement Plan

This plan is intentionally lean and execution-focused.

- **Primary outcomes (P0):** maintenance signal, security signal, proof of reliability
- **Secondary outcomes (P1):** restrained feature depth, docs as product
- **Deferred outcomes (P2):** community ecosystem (after P0/P1 foundation is stable)

## KPI Targets (end of week 12)

- **Issue response SLA:** first maintainer response within **48h** for >= **90%** of new issues
- **Release cadence:** at least **1 tagged release every 2 weeks** (>= 6 releases in 12 weeks)
- **CI + security health:**
  - CI default branch pass rate >= **95%**
  - Dependency and secrets scan workflows passing on default branch >= **95%** of runs
  - High/critical dependency vulnerabilities in default branch = **0 open > 7 days**
- **Onboarding success:**
  - >= **80%** of fresh setups complete `make first-run` + `make smoke` in <= **20 minutes** (tracked via internal test log)
- **Reliability proof:**
  - Local benchmark success rate >= **99%** on baseline run
  - p95 request latency for benchmark endpoint <= **300ms** on local baseline

## Weekly Milestones (12 weeks)

### Week 1 — Baseline + immediate trust signals

- Ship this plan and align docs to current structure
- Add actionable release/security checklist
- Add benchmark script and reproducible command
- Expand FAQ/troubleshooting for known pitfalls

**Definition of done**
- Plan merged in `docs/90-day-score-plan.md`
- README + release checklist + shims status + benchmark docs merged
- Baseline benchmark result captured in PR notes

### Week 2 — Operating rhythm

- Start issue triage cadence
- Label/triage conventions documented
- Begin SLA tracking for first response

**Definition of done**
- Triage routine documented and used for all new issues this week
- 100% of new issues have labels and owner/next action

### Week 3 — CI confidence tightening

- Add/adjust workflow gates for test + lint consistency
- Define CI failure triage rule (who/when/how)

**Definition of done**
- CI gate policy documented
- CI failures have assigned follow-up within 24h

### Week 4 — Security signal hardening

- Tighten dependency/security scan handling workflow
- Add explicit remediation timeline rules

**Definition of done**
- Security findings routing documented
- High/critical findings tracked with due dates

### Week 5 — Release cadence start

- Publish release template/check discipline
- Execute first cadence release under new checklist

**Definition of done**
- One tagged release published with complete checklist evidence

### Week 6 — Release cadence repeatability

- Execute second cadence release
- Review release notes quality and migration clarity

**Definition of done**
- Two consecutive on-time cadence releases complete

### Week 7 — Onboarding friction pass

- Validate quickstart on fresh environment
- Collect top 3 onboarding blockers and fix docs

**Definition of done**
- Onboarding runbook updated
- Time-to-first-success measured for at least 5 runs

### Week 8 — Docs as product (P1)

- Consolidate operational docs for daily use
- Improve discoverability/navigation in docs index

**Definition of done**
- Docs navigation updated and cross-linked
- Top operational tasks each have one canonical page

### Week 9 — Reliability instrumentation pass

- Define reliability baseline report format
- Capture benchmark trend from at least 3 runs

**Definition of done**
- Reliability snapshot committed (metrics + interpretation)

### Week 10 — Reliability guardrails

- Add lightweight regression threshold checks for reliability benchmark

**Definition of done**
- Thresholds documented and validated in CI/local workflow

### Week 11 — Maintenance throughput review

- Review SLA, cadence, CI/security trend vs KPIs
- Correct process bottlenecks only (no major feature work)

**Definition of done**
- KPI scorecard updated with current numbers and gaps

### Week 12 — Consolidation + next-quarter handoff

- Publish 90-day retrospective and next-quarter priority queue
- Keep P2 community work explicitly scoped after P0/P1 stability

**Definition of done**
- Retrospective doc merged
- Next-quarter backlog ranked with rationale

## Risk controls and anti-overengineering guardrails

- Prefer **docs/process fixes** over new feature code unless reliability/security is blocked
- Any new implementation work must include: clear problem statement, rollback path, and measurable success criteria
- Keep PRs small: target <= 300 lines net change unless justified
- No framework/tool churn during this 90-day window
- Time-box experiments to <= 1 day; convert to issue if not done
- Avoid introducing new infra dependencies unless directly tied to P0 reliability/security KPIs

## Execution queue (remaining tracks as issues)

The following issues track the remaining 90-day work:

- [#28](https://github.com/Dunrip/dunrip-webhook-bridge/issues/28) — CI reliability gate and failure-triage policy (Weeks 3–4)
- [#29](https://github.com/Dunrip/dunrip-webhook-bridge/issues/29) — Security remediation SLA and release-hardening workflow (Weeks 4–6)
- [#30](https://github.com/Dunrip/dunrip-webhook-bridge/issues/30) — Onboarding success measurement and doc-led friction reduction (Weeks 7–8)
- [#31](https://github.com/Dunrip/dunrip-webhook-bridge/issues/31) — Reliability benchmark trend + regression guardrail (Weeks 9–10)
- [#32](https://github.com/Dunrip/dunrip-webhook-bridge/issues/32) — KPI scorecard + 90-day retrospective + next-quarter queue (Weeks 11–12)
