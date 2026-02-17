#!/bin/sh
set -eu

fail() {
  echo "❌ $1" >&2
  exit 1
}

info() {
  echo "ℹ️  $1"
}

ok() {
  echo "✅ $1"
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PROJECT_ROOT/$ENV_FILE" ;;
esac

[ -f "$ENV_FILE" ] || fail "Environment file not found: $ENV_FILE\n   Fix: run 'make wizard' or set ENV_FILE=/path/to/.env"

# shellcheck disable=SC1090
set -a
. "$ENV_FILE"
set +a

[ -n "${GITHUB_WEBHOOK_SECRET:-}" ] || fail "GITHUB_WEBHOOK_SECRET is empty in $ENV_FILE\n   Fix: run 'make wizard' and generate/set a secret"

command -v curl >/dev/null 2>&1 || fail "Missing command: curl"
command -v python3 >/dev/null 2>&1 || fail "Missing command: python3"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

payload_file="$tmp_dir/github-payload.json"
cat > "$payload_file" <<'JSON'
{"zen":"Keep it logically awesome.","hook_id":1}
JSON

sig=$(python3 - "$payload_file" "$GITHUB_WEBHOOK_SECRET" <<'PY'
import hashlib, hmac, pathlib, sys
payload = pathlib.Path(sys.argv[1]).read_bytes()
secret = sys.argv[2].encode()
print('sha256=' + hmac.new(secret, payload, hashlib.sha256).hexdigest())
PY
)

resp_file="$tmp_dir/response.json"
info "Sending signed GitHub ping event to $BASE_URL/webhook/github"
status=$(curl -sS -o "$resp_file" -w "%{http_code}" \
  -X POST "$BASE_URL/webhook/github" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-GitHub-Delivery: manual-test-delivery" \
  -H "X-Hub-Signature-256: $sig" \
  --data-binary "@$payload_file") || fail "Request failed\n   Fix: make sure service is running: 'make up'"

if [ "$status" != "200" ]; then
  echo "Received HTTP $status"
  if [ "$status" = "401" ]; then
    fail "Signature rejected\n   Fix: ensure .env GITHUB_WEBHOOK_SECRET matches the GitHub webhook secret"
  fi
  if [ "$status" = "404" ]; then
    fail "Endpoint not found\n   Fix: verify BASE_URL points to webhook-bridge (current: $BASE_URL)"
  fi
  fail "Unexpected response from /webhook/github\n   Fix: check logs with 'docker compose -f deploy/docker-compose.yml logs -f webhook-bridge'"
fi

if ! python3 - "$resp_file" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
if obj.get('status') != 'pong':
    raise SystemExit(1)
PY
then
  fail "Request returned HTTP 200 but response body was unexpected\n   Fix: check service logs: 'docker compose -f deploy/docker-compose.yml logs -f webhook-bridge'"
fi

ok "GitHub webhook test passed (/webhook/github returned status=pong)"
echo "Next: configure GitHub webhook using values from 'make wizard' output."
