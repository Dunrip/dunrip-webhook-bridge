#!/usr/bin/env python3
"""Lightweight local benchmark for reliability proof.

Example:
  python3 scripts/benchmark_local.py --url http://127.0.0.1:8000/health --requests 300 --concurrency 20
"""

from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import time
import urllib.error
import urllib.request


def one_request(url: str, timeout: float) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 (local benchmark utility)
            ok = 200 <= resp.status < 400
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        ok = False
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return ok, elapsed_ms


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[k]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight local benchmark.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health", help="Target URL")
    parser.add_argument("--requests", type=int, default=200, help="Total requests")
    parser.add_argument("--concurrency", type=int, default=10, help="Worker threads")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-request timeout seconds")
    args = parser.parse_args()

    total = max(1, args.requests)
    workers = max(1, min(args.concurrency, total))

    started = time.perf_counter()
    results: list[tuple[bool, float]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_request, args.url, args.timeout) for _ in range(total)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    wall_ms = (time.perf_counter() - started) * 1000.0

    successes = sum(1 for ok, _ in results if ok)
    latencies = sorted(lat for _, lat in results)

    success_rate = (successes / total) * 100.0
    avg_ms = statistics.mean(latencies) if latencies else 0.0
    p95_ms = percentile(latencies, 95)
    max_ms = max(latencies) if latencies else 0.0
    rps = total / (wall_ms / 1000.0) if wall_ms > 0 else 0.0

    print("Local benchmark results")
    print(f"URL: {args.url}")
    print(f"Requests: {total}")
    print(f"Concurrency: {workers}")
    print(f"Success: {successes}/{total} ({success_rate:.2f}%)")
    print(f"Latency ms: avg={avg_ms:.2f} p95={p95_ms:.2f} max={max_ms:.2f}")
    print(f"Throughput: {rps:.2f} req/s")

    return 0 if successes == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
