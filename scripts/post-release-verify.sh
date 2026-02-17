#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
RELEASE_VERSION="${RELEASE_VERSION:-}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$PROJECT_ROOT/docs/release-evidence}"
BENCHMARK_BASELINE_FILE="${BENCHMARK_BASELINE_FILE:-}"
BENCHMARK_CURRENT_FILE="${BENCHMARK_CURRENT_FILE:-}"
BENCHMARK_P95_THRESHOLD_PCT="${BENCHMARK_P95_THRESHOLD_PCT:-20}"

stamp=$(date +%Y%m%d-%H%M%S)
label="$stamp"
if [ -n "$RELEASE_VERSION" ]; then
  label="$RELEASE_VERSION-$stamp"
fi

evidence_dir="$EVIDENCE_ROOT/$label"
mkdir -p "$evidence_dir"

echo "▶ Collecting post-release evidence into: $evidence_dir"

curl_json() {
  path="$1"
  out="$2"
  code_file="$out.code"
  curl -sS -o "$out" -w "%{http_code}" "$BASE_URL$path" > "$code_file"
}

curl_json "/health" "$evidence_dir/health.json"
health_code=$(cat "$evidence_dir/health.json.code")

curl_json "/health/deep" "$evidence_dir/health-deep.json"
deep_code=$(cat "$evidence_dir/health-deep.json.code")

curl -sS "$BASE_URL/metrics" | head -n 80 > "$evidence_dir/metrics-head.txt"

python3 - "$evidence_dir" "$health_code" "$deep_code" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
health_code = int(sys.argv[2])
deep_code = int(sys.argv[3])
health = json.loads((root / "health.json").read_text(encoding="utf-8"))
deep = json.loads((root / "health-deep.json").read_text(encoding="utf-8"))

if health_code != 200:
    raise SystemExit(f"/health HTTP {health_code} (expected 200)")
if health.get("status") != "ok":
    raise SystemExit(f"/health status unexpected: {health}")
if deep_code not in (200, 503):
    raise SystemExit(f"/health/deep HTTP {deep_code} (expected 200 or 503)")
if "status" not in deep or "circuit_breaker" not in deep:
    raise SystemExit(f"/health/deep payload unexpected: {deep}")
PY

git_remote=$(git remote get-url origin 2>/dev/null || true)
repo_slug=""
case "$git_remote" in
  git@github.com:*)
    repo_slug=$(printf "%s" "$git_remote" | sed -E 's#^git@github.com:([^ ]+?)(\.git)?$#\1#')
    ;;
  https://github.com/*|http://github.com/*)
    repo_slug=$(printf "%s" "$git_remote" | sed -E 's#^https?://github.com/([^ ]+?)(\.git)?/?$#\1#')
    ;;
esac

if command -v gh >/dev/null 2>&1 && [ -n "$repo_slug" ]; then
  if ! gh api "repos/$repo_slug/actions/runs?per_page=20" > "$evidence_dir/workflow-runs.json" 2> "$evidence_dir/workflow-runs.err"; then
    err_text=$(tr '\n' ' ' < "$evidence_dir/workflow-runs.err" | sed 's/"/\\"/g')
    printf '{"status":"error","repo_slug":"%s","error":"%s"}\n' "$repo_slug" "$err_text" > "$evidence_dir/workflow-runs.json"
  fi
else
  printf '{"status":"skipped","reason":"gh CLI not available or repo slug unresolved","git_remote":"%s"}\n' "$git_remote" > "$evidence_dir/workflow-runs.json"
fi

if [ -n "$BENCHMARK_BASELINE_FILE" ] && [ -n "$BENCHMARK_CURRENT_FILE" ] && [ -f "$BENCHMARK_BASELINE_FILE" ] && [ -f "$BENCHMARK_CURRENT_FILE" ]; then
  python3 - "$BENCHMARK_BASELINE_FILE" "$BENCHMARK_CURRENT_FILE" "$BENCHMARK_P95_THRESHOLD_PCT" "$evidence_dir/benchmark-compare.json" <<'PY'
import json
import pathlib
import sys

baseline = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
current = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
threshold = float(sys.argv[3])
out = pathlib.Path(sys.argv[4])

bp95 = float(baseline.get("p95_ms", 0.0))
cp95 = float(current.get("p95_ms", 0.0))
status = "not-comparable"
if bp95 > 0:
    change_pct = ((cp95 - bp95) / bp95) * 100.0
    status = "ok" if change_pct <= threshold else "regression"
else:
    change_pct = None

result = {
    "baseline": baseline,
    "current": current,
    "p95_threshold_pct": threshold,
    "p95_change_pct": change_pct,
    "status": status,
}
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
PY
else
  printf '{"status":"skipped","reason":"benchmark files not provided"}\n' > "$evidence_dir/benchmark-compare.json"
fi

cat > "$evidence_dir/summary.md" <<EOF_SUM
# Post-release verification summary

- Base URL: \
`$BASE_URL`
- Release version: \
`${RELEASE_VERSION:-not-set}`
- Generated at: \
`$(date -u +%Y-%m-%dT%H:%M:%SZ)`

## Health checks

- /health HTTP: $health_code
- /health/deep HTTP: $deep_code

## Evidence files

- health.json
- health-deep.json
- metrics-head.txt
- workflow-runs.json
- benchmark-compare.json
EOF_SUM

echo "✅ Post-release evidence captured: $evidence_dir"
echo "$evidence_dir"
