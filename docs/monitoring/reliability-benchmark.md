# Reliability Benchmark Baseline & Regression Guardrail

Local benchmark script: `scripts/benchmark_local.py`

## What it measures

- request latency distribution (`p50_ms`, `p95_ms`, `max_ms`)
- error rate (`error_rate`)

## Local usage

Run quick benchmark:

```bash
make benchmark ITERATIONS=100
```

Create/update baseline:

```bash
make benchmark-baseline ITERATIONS=200 BASELINE=.benchmarks/local-baseline.json
```

Compare current run against baseline and fail on regression:

```bash
make benchmark-compare \
  ITERATIONS=200 \
  BASELINE=.benchmarks/local-baseline.json \
  MAX_P95_REGRESSION_PCT=20 \
  MAX_ERROR_RATE_REGRESSION_ABS=0.01
```

## CI usage pattern

Use compare mode as a guard step. If p95 or error rate exceed thresholds, script exits non-zero.

Example:

```bash
PYTHONPATH=. .venv/bin/python scripts/benchmark_local.py \
  --iterations 200 \
  --compare-baseline .benchmarks/local-baseline.json \
  --max-p95-regression-pct 20 \
  --max-error-rate-regression-abs 0.01
```

Tip: refresh baseline intentionally (not automatically on every run) after approved performance improvements.
