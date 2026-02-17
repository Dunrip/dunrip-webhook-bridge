# Operator Troubleshooting Decision Tree (Fast Path)

Use this when setup or post-release checks fail. Follow top-down and stop as soon as you find the fix.

## 1) Is the service reachable?

```bash
BASE_URL=${BASE_URL:-http://127.0.0.1:8000}
curl -fsS "$BASE_URL/health" | python3 -m json.tool
```

- Fails to connect / timeout:
  - Start stack: `make up`
  - Check logs: `docker compose -f deploy/docker-compose.yml logs -f webhook-bridge`
- Returns non-200:
  - Run diagnostics: `make doctor`
  - Check `.env` validity and required vars.

## 2) Is downstream health degraded?

```bash
curl -sS "$BASE_URL/health/deep" | python3 -m json.tool
```

- `status=degraded` or circuit breaker open:
  - Verify Telegram token/chat ID in `.env`
  - Check outbound network access to Telegram API
  - Restart service: `docker compose -f deploy/docker-compose.yml restart webhook-bridge`
  - See: `docs/runbooks/circuit-breaker-open.md`

## 3) Is webhook signature validation failing (401)?

For GitHub webhooks returning invalid signature:

- Confirm GitHub webhook **Secret** exactly matches `GITHUB_WEBHOOK_SECRET` from `.env`.
- Re-run signed ping:

```bash
make test-github
```

- If still failing, re-open GitHub webhook settings and paste the secret again.

## 4) Are admin endpoints failing (401 on `/deliveries`)?

- Prefer scoped keys with `ADMIN_API_KEYS`, or legacy single key with `ADMIN_API_KEY`.
- If both are set, scoped keys take precedence.
- Validate with:

```bash
make doctor
```

## 5) Need one-shot full operational check?

```bash
make smoke
```

This validates `/health`, `/health/deep`, `/metrics`, signed GitHub webhook ping, and (if configured) admin auth checks.

---

## Copy/Paste Playbook: Recover from env mismatch after edits

Symptoms:
- App still uses old token/secret after `.env` update
- smoke/doctor indicates key mismatch

Run exactly:

```bash
cp -n .env.example .env
make wizard

docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml --env-file .env up -d --force-recreate

make doctor
make smoke
```

Expected outcome:
- doctor reports healthy config
- smoke passes (or gives actionable degraded hints)
