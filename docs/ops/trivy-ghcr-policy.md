# Trivy GHCR Gate Policy

This policy defines how container vulnerability findings are handled in `Publish GHCR Image`.

## Scope

- Scanner: Trivy (`aquasecurity/trivy-action`)
- Artifact: `ghcr.io/dunrip/dunrip-webhook-bridge`
- Findings scope: `CRITICAL,HIGH`
- Scanners: `vuln` (OS + library vulnerabilities)
- `ignore-unfixed: true` (focus on actionable fixes)
- Secret scanning remains covered by `Security - Secrets Scan` (gitleaks)

## Gate Modes

### 1) Non-release mode (push to `main`)
- **Mode:** `non-blocking-main`
- **Exit code:** `0`
- **Behavior:** Workflow stays green while still publishing SARIF + summary.
- **Goal:** Keep delivery flow stable while surfacing risk continuously.

### 2) Release mode (tag `v*`)
- **Mode:** `blocking-release`
- **Exit code:** `1`
- **Behavior:** Workflow fails if CRITICAL/HIGH actionable findings exist.
- **Goal:** Prevent shipping a tagged release with unaccepted high-risk findings.

## Baseline & Suppression Strategy

Known accepted findings are tracked in `.trivyignore`.

Each suppression entry must include:
- Owner
- Reason
- Tracking issue/PR
- Expiry date (UTC)

Expired entries must be removed or explicitly renewed with updated justification.

## Remediation SLA

Use `SECURITY.md` severity targets as default remediation timeline:
- Critical: acknowledge within 24h, mitigation plan within 72h, patch target within 7 days
- High: acknowledge within 2 business days, fix plan within 5 business days, patch target within 14 days

## CI Summary Requirements

`Publish GHCR Image` writes a step summary with:
- Active gate mode
- Blocking/non-blocking exit behavior
- Scan scope and ignore-unfixed policy
- Baseline source (`.trivyignore`)
- Link to this policy

## Operational Workflow

1. Review SARIF findings in GitHub Security tab.
2. If fixable quickly, patch dependencies/base image and rerun.
3. If not immediately fixable, create/attach tracking issue.
4. Only add suppression with owner + expiry + rationale.
5. Before tag/release, confirm no unaccepted CRITICAL/HIGH findings.
