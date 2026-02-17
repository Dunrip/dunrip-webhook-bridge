#!/usr/bin/env python3
"""Local reliability benchmark with optional baseline regression guardrails.

Examples:
  # Run benchmark and print metrics
  PYTHONPATH=. python scripts/benchmark_local.py

  # Save baseline for future runs
  PYTHONPATH=. python scripts/benchmark_local.py --baseline-out .benchmarks/local-baseline.json

  # Compare with baseline and fail if regressions exceed thresholds
  PYTHONPATH=. python scripts/benchmark_local.py \
    --compare-baseline .benchmarks/local-baseline.json \
    --max-p95-regression-pct 20 \
    --max-error-rate-regression-abs 0.01
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import statistics
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _pctl(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return values[low]
    weight = rank - low
    return values[low] * (1 - weight) + values[high] * weight


def run_benchmark(iterations: int, event_type: str = "push") -> dict[str, float | int | str]:
    # Keep benchmark deterministic and network-free.
    main.settings.github_webhook_secret = "gh-secret"
    main.settings.storage_backend = "memory"
    main.settings.rate_limit_backend = "memory"
    main.settings.rate_limit_ip_per_minute = 100000
    main.settings.rate_limit_token_per_minute = 100000

    async def fake_send(_: str) -> None:
        return None

    main.send_message = fake_send

    app = main.create_app()
    payload = json.dumps({"repository": {"full_name": "org/repo"}, "commits": []}).encode()

    statuses: list[int] = []
    durations_ms: list[float] = []

    with TestClient(app) as client:
        for i in range(iterations):
            started = time.perf_counter()
            response = client.post(
                "/webhook/github",
                content=payload,
                headers={
                    "X-Hub-Signature-256": _sign(payload, "gh-secret"),
                    "X-GitHub-Event": event_type,
                    "X-GitHub-Delivery": f"bench-{i}",
                },
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            durations_ms.append(elapsed_ms)
            statuses.append(response.status_code)

    total = len(statuses)
    failures = sum(1 for status in statuses if status >= 400)
    error_rate = failures / total if total else 0.0

    sorted_durations = sorted(durations_ms)
    return {
        "iterations": total,
        "event_type": event_type,
        "error_rate": round(error_rate, 6),
        "avg_ms": round(statistics.mean(durations_ms), 3),
        "p50_ms": round(_pctl(sorted_durations, 0.50), 3),
        "p95_ms": round(_pctl(sorted_durations, 0.95), 3),
        "max_ms": round(max(sorted_durations) if sorted_durations else 0.0, 3),
        "timestamp": int(time.time()),
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare(
    current: dict[str, float | int | str],
    baseline: dict[str, float | int | str],
    *,
    max_p95_regression_pct: float,
    max_error_rate_regression_abs: float,
) -> tuple[bool, list[str]]:
    msgs: list[str] = []
    ok = True

    baseline_p95 = float(baseline.get("p95_ms", 0.0))
    current_p95 = float(current.get("p95_ms", 0.0))
    allowed_p95 = baseline_p95 * (1 + max_p95_regression_pct / 100)
    if current_p95 > allowed_p95:
        ok = False
        msgs.append(
            f"p95 regression: current={current_p95:.3f}ms baseline={baseline_p95:.3f}ms allowed={allowed_p95:.3f}ms"
        )

    baseline_error = float(baseline.get("error_rate", 0.0))
    current_error = float(current.get("error_rate", 0.0))
    allowed_error = baseline_error + max_error_rate_regression_abs
    if current_error > allowed_error:
        ok = False
        msgs.append(
            f"error-rate regression: current={current_error:.6f} baseline={baseline_error:.6f} allowed={allowed_error:.6f}"
        )

    if ok:
        msgs.append("benchmark compare: OK")
    return ok, msgs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local webhook reliability benchmark")
    parser.add_argument("--iterations", type=int, default=100, help="Number of benchmark requests")
    parser.add_argument("--event-type", default="push", help="GitHub event type to benchmark")
    parser.add_argument("--baseline-out", type=Path, help="Write benchmark JSON baseline to this file")
    parser.add_argument("--compare-baseline", type=Path, help="Compare current run against this baseline JSON")
    parser.add_argument(
        "--max-p95-regression-pct",
        type=float,
        default=20.0,
        help="Allowed p95 latency regression percentage vs baseline",
    )
    parser.add_argument(
        "--max-error-rate-regression-abs",
        type=float,
        default=0.01,
        help="Allowed absolute error-rate regression vs baseline",
    )
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()
    if args.iterations <= 0:
        raise SystemExit("--iterations must be > 0")

    result = run_benchmark(args.iterations, event_type=args.event_type)
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.baseline_out:
        _save_json(args.baseline_out, result)
        print(f"baseline written: {args.baseline_out}")

    if args.compare_baseline:
        baseline = _load_json(args.compare_baseline)
        ok, messages = compare(
            result,
            baseline,
            max_p95_regression_pct=args.max_p95_regression_pct,
            max_error_rate_regression_abs=args.max_error_rate_regression_abs,
        )
        for msg in messages:
            print(msg)
        if not ok:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
