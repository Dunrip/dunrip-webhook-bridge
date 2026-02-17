# Weekly KPI Scorecard Template

Use one file/copy per week (or keep as a running table in your ops notebook).

## Week Metadata

- Week of: `YYYY-MM-DD`
- Release(s): `vX.Y.Z` (if any)
- Operator:

## Scorecard

| KPI | Target | Actual | Status (✅/⚠️/❌) | Evidence |
| --- | --- | --- | --- | --- |
| Service SLA (uptime) | >= 99.9% |  |  | Link to uptime panel/report |
| Release cadence | Planned release window met |  |  | Release tag + notes |
| CI health | 100% required workflows green on default branch |  |  | Actions run URLs |
| Onboarding success | First-run complete in <= 15 min (new operator dry run) |  |  | Checklist notes/screenshot |
| Reliability benchmark trend | No >20% regression vs baseline |  |  | Benchmark compare artifact |

## Notes

- What improved this week:
- Regressions / incidents:
- Follow-up actions:

## Evidence bundle

Store post-release verification evidence under:

- `docs/release-evidence/<release-or-date>/`

Minimum evidence set:
- health checks (`health.json`, `health-deep.json`, `metrics-head.txt`)
- workflow status snapshot (`workflow-runs.json`)
- benchmark comparison (or explicit "not available" note)
