#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/deploy/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PROJECT_ROOT/$ENV_FILE" ;;
esac

errors=0
warns=0

ok() { echo "✅ $1"; }
warn() { echo "⚠️  $1"; warns=$((warns + 1)); }
err() { echo "❌ $1"; errors=$((errors + 1)); }

require_var() {
  key="$1"
  eval "val=\${$key:-}"
  if [ -n "$val" ]; then
    ok "$key is set"
  else
    err "$key is missing"
    echo "   Fix: run 'make wizard' and set $key"
  fi
}

check_empty_numeric() {
  key="$1"
  default="$2"
  if [ -f "$ENV_FILE" ] && grep -Eq "^[[:space:]]*$key=[[:space:]]*$" "$ENV_FILE"; then
    warn "$key is present but empty in .env (runtime default: $default). Set an explicit value or remove the line."
  fi
}

echo "Webhook Bridge Doctor"
echo "Project root: $PROJECT_ROOT"

# Docker checks
if ! command -v docker >/dev/null 2>&1; then
  err "docker is not installed"
  echo "   Fix: install Docker Desktop, then run 'make up'"
else
  ok "docker command found"
  if docker info >/dev/null 2>&1; then
    ok "docker daemon is reachable"
  else
    err "docker daemon is not reachable"
    echo "   Fix: start Docker Desktop (or daemon), then retry"
  fi
fi

# .env checks
if [ -f "$ENV_FILE" ]; then
  ok ".env found at $ENV_FILE"
else
  err ".env not found at $ENV_FILE"
  echo "   Fix: run 'make setup' or 'make wizard', or set ENV_FILE=/path/to/.env"
fi

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$ENV_FILE"
  set +a

  require_var TELEGRAM_BOT_TOKEN
  require_var TELEGRAM_CHAT_ID
  require_var GITHUB_WEBHOOK_SECRET
  require_var GENERIC_WEBHOOK_TOKEN

  if [ -n "${ADMIN_API_KEYS_ACTIVE:-}" ] || [ -n "${ADMIN_API_KEYS_PREVIOUS:-}" ] || [ -n "${ADMIN_API_KEYS:-}" ]; then
    ok "Scoped admin key config detected (ADMIN_API_KEYS*)"
    if [ -n "${ADMIN_API_KEY:-}" ]; then
      warn "Conflicting admin auth vars: ADMIN_API_KEYS* and ADMIN_API_KEY are both set. Runtime will use scoped keys."
      echo "   Fix: keep one mode only. Recommended: remove ADMIN_API_KEY from .env"
      echo "   Alternative: clear ADMIN_API_KEYS* if you intentionally want legacy ADMIN_API_KEY mode"
    fi
  elif [ -n "${ADMIN_API_KEY:-}" ]; then
    ok "Legacy ADMIN_API_KEY is set"
  else
    err "Missing admin auth config. Set ADMIN_API_KEYS (preferred) or ADMIN_API_KEY."
    echo "   Fix: run 'make wizard' and add at least one admin key"
  fi

  check_empty_numeric ADMIN_KEY_ROTATION_GRACE_SECONDS 604800
  check_empty_numeric MAX_BODY_SIZE 1048576
  check_empty_numeric IDEMPOTENCY_TTL 3600
  check_empty_numeric FAILED_DELIVERY_TTL 604800
  check_empty_numeric TELEGRAM_RETRIES 2
  check_empty_numeric CIRCUIT_BREAKER_THRESHOLD 5
  check_empty_numeric CIRCUIT_BREAKER_TIMEOUT 60
  check_empty_numeric RATE_LIMIT_IP_PER_MINUTE 10
  check_empty_numeric RATE_LIMIT_TOKEN_PER_MINUTE 30
  check_empty_numeric RATE_LIMIT_ADMIN_PER_MINUTE 20
  check_empty_numeric WS_CONNECTS_PER_MINUTE 10
  check_empty_numeric WS_MAX_CONNECTIONS_PER_IP 3
  check_empty_numeric REPLAY_COOLDOWN_SECONDS 30
  check_empty_numeric MAX_REPLAY_ATTEMPTS 10
fi

# Compose + runtime mismatch checks
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if docker compose --project-directory "$PROJECT_ROOT" -f "$COMPOSE_FILE" config >/tmp/webhook-bridge-compose-doctor.txt 2>/tmp/webhook-bridge-compose-doctor.err; then
    if grep -q "ADMIN_API_KEY:" /tmp/webhook-bridge-compose-doctor.txt; then
      ok "docker compose config includes ADMIN_API_KEY mapping"
    else
      err "docker compose config is missing ADMIN_API_KEY mapping"
      echo "   Fix: add ADMIN_API_KEY env mapping under webhook-bridge service"
    fi

    cid=$(docker compose --project-directory "$PROJECT_ROOT" -f "$COMPOSE_FILE" ps -q webhook-bridge || true)
    if [ -n "$cid" ]; then
      runtime_admin=$(docker inspect --format='{{range .Config.Env}}{{println .}}{{end}}' "$cid" | awk -F= '$1=="ADMIN_API_KEY" {sub(/^ADMIN_API_KEY=/, "", $0); print $0}')
      if [ -n "${ADMIN_API_KEY:-}" ] && [ -n "$runtime_admin" ] && [ "$runtime_admin" != "$ADMIN_API_KEY" ]; then
        warn "Running container ADMIN_API_KEY differs from .env."
        echo "   Fix: docker compose --project-directory . -f deploy/docker-compose.yml up -d --force-recreate webhook-bridge"
      else
        ok "No ADMIN_API_KEY runtime mismatch detected"
      fi

      health_code=$(curl -sS -o /tmp/webhook-bridge-health-doctor.json -w "%{http_code}" "$BASE_URL/health" || true)
      if [ "$health_code" = "200" ]; then
        ok "/health reachable at $BASE_URL/health"
      else
        err "webhook-bridge container is running but /health is not reachable (HTTP $health_code)"
        echo "   Fix: check logs with 'docker compose logs -f webhook-bridge'"
        echo "   Fix: confirm port mapping and BASE_URL (current: $BASE_URL)"
      fi
    else
      warn "webhook-bridge container is not running; runtime checks and /health reachability skipped"
      echo "   Hint: start service with 'make up'"
    fi
  else
    err "docker compose config check failed"
    echo "   Details: $(cat /tmp/webhook-bridge-compose-doctor.err)"
    echo "   Fix: validate deploy/docker-compose.yml and .env variable interpolation"
  fi
fi

if [ "$errors" -gt 0 ]; then
  echo ""
  echo "Doctor found $errors critical issue(s) and $warns warning(s)."
  exit 1
fi

echo ""
echo "Doctor completed with $warns warning(s)."
