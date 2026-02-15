# Security Incident Runbook

Use this runbook for suspected compromise, abuse, or forgery affecting webhook ingestion and delivery.

## 1) API key leak response

1. **Declare incident + assign lead**
   - Open an incident channel and assign incident commander.
2. **Contain immediately**
   - Rotate leaked keys/secrets at the provider and in deployment env:
     - `ADMIN_API_KEY`
     - `TELEGRAM_BOT_TOKEN`
     - `GITHUB_WEBHOOK_SECRET`
     - `GENERIC_WEBHOOK_TOKEN`
   - Revoke old keys/tokens.
3. **Limit blast radius**
   - Temporarily restrict admin endpoints at edge/network if needed.
   - Invalidate active sessions/connections where applicable.
4. **Assess impact**
   - Review logs for unauthorized admin access, replay attempts, and unusual source IPs.
   - Identify time window from first exposure to rotation completion.
5. **Recover + harden**
   - Redeploy with new secrets.
   - Verify health checks and signed webhook validation are passing.
   - Add/adjust monitoring alerts for similar patterns.

## 2) Replay abuse response

1. **Detect + confirm**
   - Confirm elevated `replay` activity and repeated delivery IDs in logs/metrics.
2. **Contain**
   - Enforce stricter temporary limits:
     - Lower `RATE_LIMIT_ADMIN_PER_MINUTE`
     - Increase `REPLAY_COOLDOWN_SECONDS`
     - Lower `MAX_REPLAY_ATTEMPTS` if necessary
   - Block abusive IPs at WAF/reverse proxy.
3. **Eradicate**
   - Rotate `ADMIN_API_KEY` if abuse involved valid credentials.
   - Investigate idempotency key usage and duplicate request patterns.
4. **Recover**
   - Restore safe baseline limits after abuse subsides.
   - Reprocess only verified failed deliveries.

## 3) Webhook spoofing validation checklist

- [ ] Verify endpoint requires signature/token validation (`/webhook/github`, generic route).
- [ ] Confirm secret in provider exactly matches deployed env secret.
- [ ] Confirm request rejection on missing/invalid signatures (401 expected).
- [ ] Validate timestamp/nonce controls (if enabled) and replay protections.
- [ ] Check suspicious requests for:
  - [ ] unknown source IP / ASN
  - [ ] malformed signature header
  - [ ] unusual user-agent or payload shape
- [ ] Confirm only expected events are accepted/processed.

## 4) Post-incident communication checklist

- [ ] Create incident timeline (detection, containment, recovery, closure).
- [ ] Record root cause and contributing factors.
- [ ] Document affected systems, data, and customer impact.
- [ ] Publish internal postmortem with corrective actions + owners + deadlines.
- [ ] Notify external stakeholders/customers (if required by policy/law).
- [ ] Update runbooks, alerts, and tests based on lessons learned.

## Appendix: CI security hygiene controls

- Dependency scanning: `.github/workflows/security-deps.yml` (pip-audit, fails on vulnerabilities)
- Secrets scanning: `.github/workflows/security-secrets.yml` (gitleaks, fails on findings)
- Gitleaks allowlist config: `.gitleaks.toml` (currently minimal; add only justified exceptions)
