#!/bin/sh
set -eu

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"

if [ ! -f "$ENV_FILE" ]; then
  if [ ! -f "$EXAMPLE_FILE" ]; then
    echo "❌ Missing $EXAMPLE_FILE. Cannot bootstrap environment." >&2
    exit 1
  fi
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  echo "✅ Created $ENV_FILE from $EXAMPLE_FILE"
fi

# shellcheck disable=SC1090
set -a
. "$ENV_FILE"
set +a

missing_required=""

check_required() {
  key="$1"
  value="${2:-}"
  lower_value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$lower_value" in
    ""|your-*|"<"*">")
      missing_required="$missing_required $key"
      ;;
  esac
}

check_required "TELEGRAM_BOT_TOKEN" "${TELEGRAM_BOT_TOKEN:-}"
check_required "TELEGRAM_CHAT_ID" "${TELEGRAM_CHAT_ID:-}"
check_required "GITHUB_WEBHOOK_SECRET" "${GITHUB_WEBHOOK_SECRET:-}"
check_required "ADMIN_API_KEY" "${ADMIN_API_KEY:-}"

GENERIC_ROUTE_ENABLED="${GENERIC_ROUTE_ENABLED:-true}"
case "$(printf '%s' "$GENERIC_ROUTE_ENABLED" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    check_required "GENERIC_WEBHOOK_TOKEN" "${GENERIC_WEBHOOK_TOKEN:-}"
    ;;
esac

if [ -n "$missing_required" ]; then
  echo ""
  echo "❌ Setup incomplete. Missing required environment values:"
  for key in $missing_required; do
    echo "  - $key"
  done
  echo ""
  echo "Common fixes:"
  echo "  1) Run: make wizard"
  echo "  2) Or edit .env manually and fill each missing value"
  echo "  3) TELEGRAM_CHAT_ID can be retrieved from:"
  echo "     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
  echo ""
  echo "Next step after fixing values: make up && make smoke"
  exit 1
fi

echo "✅ Environment bootstrap check passed."
echo "Next steps:"
echo "  1) Start the service: make up"
echo "  2) Run smoke tests: make smoke"
