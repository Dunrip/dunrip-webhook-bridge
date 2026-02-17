#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PROJECT_ROOT/$ENV_FILE" ;;
esac

symptom_help() {
  symptom="$1"
  echo ""
  echo "Likely fixes:"
  case "$symptom" in
    health)
      echo "  - Start service: make up"
      echo "  - Verify BASE_URL (current: $BASE_URL)"
      echo "  - Check logs: docker compose logs -f webhook-bridge"
      ;;
    deep)
      echo "  - Verify TELEGRAM_BOT_TOKEN in .env"
      echo "  - Check outbound network access to Telegram API"
      echo "  - Re-run after restart: docker compose restart webhook-bridge"
      ;;
    metrics)
      echo "  - Ensure app started correctly and metrics endpoint is enabled"
      echo "  - Check logs for startup errors"
      ;;
    github)
      echo "  - Ensure GITHUB_WEBHOOK_SECRET in .env is set and non-empty"
      echo "  - Recreate service to apply env changes: docker compose up -d --force-recreate webhook-bridge"
      echo "  - Verify endpoint path /webhook/github"
      ;;
    admin)
      echo "  - Set ADMIN_API_KEYS (preferred) or ADMIN_API_KEY in .env"
      echo "  - If using scoped keys, use a key with read scope for /deliveries"
      ;;
  esac
}

fail() {
  msg="$1"
  hint_key="${2:-}"
  echo "❌ $msg" >&2
  if [ -n "$hint_key" ]; then
    symptom_help "$hint_key" >&2
  fi
  exit 1
}

[ -f "$ENV_FILE" ] || fail "Environment file not found: $ENV_FILE. Set ENV_FILE=/path/to/.env if needed." health

# shellcheck disable=SC1090
set -a
. "$ENV_FILE"
set +a

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

need_cmd curl
need_cmd python3

echo "Running smoke checks against $BASE_URL"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

health_file="$tmp_dir/health.json"
code=$(curl -sS -o "$health_file" -w "%{http_code}" "$BASE_URL/health") || fail "/health request failed" health
[ "$code" = "200" ] || fail "/health returned HTTP $code (expected 200)" health
python3 - "$health_file" <<'PY' || fail "/health response did not match expected shape" health
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert obj.get('status') == 'ok', obj
PY
echo "✅ /health"

deep_file="$tmp_dir/deep.json"
deep_code=$(curl -sS -o "$deep_file" -w "%{http_code}" "$BASE_URL/health/deep") || fail "/health/deep request failed" deep
python3 - "$deep_file" "$deep_code" <<'PY' || fail "/health/deep response invalid" deep
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
code = int(sys.argv[2])
if code not in (200, 503):
    raise AssertionError(f"unexpected status code: {code}")
if 'status' not in obj or 'circuit_breaker' not in obj:
    raise AssertionError(obj)
PY
if [ "$deep_code" = "200" ]; then
  echo "✅ /health/deep"
else
  echo "⚠️  /health/deep returned 503 (service degraded)."
  symptom_help deep
fi

metrics_file="$tmp_dir/metrics.txt"
metrics_code=$(curl -sS -o "$metrics_file" -w "%{http_code}" "$BASE_URL/metrics") || fail "/metrics request failed" metrics
[ "$metrics_code" = "200" ] || fail "/metrics returned HTTP $metrics_code" metrics
grep -q "webhook_requests_total" "$metrics_file" || fail "/metrics missing webhook_requests_total" metrics
echo "✅ /metrics"

[ -n "${GITHUB_WEBHOOK_SECRET:-}" ] || fail "GITHUB_WEBHOOK_SECRET is required for webhook signature smoke test" github

github_payload_file="$tmp_dir/github-payload.json"
cat > "$github_payload_file" <<'JSON'
{"zen":"Keep it logically awesome.","hook_id":1}
JSON

github_sig=$(python3 - "$github_payload_file" "$GITHUB_WEBHOOK_SECRET" <<'PY'
import hashlib, hmac, pathlib, sys
payload = pathlib.Path(sys.argv[1]).read_bytes()
secret = sys.argv[2].encode()
print('sha256=' + hmac.new(secret, payload, hashlib.sha256).hexdigest())
PY
)

github_resp_file="$tmp_dir/github-resp.json"
github_code=$(curl -sS -o "$github_resp_file" -w "%{http_code}" \
  -X POST "$BASE_URL/webhook/github" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-GitHub-Delivery: smoke-test-delivery" \
  -H "X-Hub-Signature-256: $github_sig" \
  --data-binary "@$github_payload_file") || fail "GitHub webhook smoke request failed" github

[ "$github_code" = "200" ] || fail "GitHub webhook returned HTTP $github_code" github
python3 - "$github_resp_file" <<'PY' || fail "GitHub webhook response invalid" github
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
assert obj.get('status') == 'pong', obj
PY

echo "✅ /webhook/github signature + ping"

if [ -n "${SMOKE_TEST_ADMIN:-}" ] || [ -n "${ADMIN_API_KEY:-}" ]; then
  unauth_code=$(curl -sS -o "$tmp_dir/admin-unauth.json" -w "%{http_code}" "$BASE_URL/deliveries") || fail "Admin unauth request failed" admin
  [ "$unauth_code" = "401" ] || fail "Expected /deliveries without API key to return 401, got $unauth_code" admin

  if [ -z "${ADMIN_API_KEY:-}" ]; then
    fail "SMOKE_TEST_ADMIN is enabled but ADMIN_API_KEY is missing" admin
  fi

  auth_code=$(curl -sS -o "$tmp_dir/admin-auth.json" -w "%{http_code}" \
    -H "X-API-Key: $ADMIN_API_KEY" \
    "$BASE_URL/deliveries") || fail "Admin auth request failed" admin
  [ "$auth_code" = "200" ] || fail "Expected /deliveries with API key to return 200, got $auth_code" admin

  python3 - "$tmp_dir/admin-auth.json" <<'PY' || fail "Admin response shape invalid" admin
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
if 'deliveries' not in obj or 'total' not in obj:
    raise AssertionError(obj)
PY

  echo "✅ admin endpoint auth checks"
fi

echo "🎉 Smoke test passed"
