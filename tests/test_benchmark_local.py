from scripts.benchmark_local import compare


def test_compare_ok_within_thresholds() -> None:
    ok, messages = compare(
        {"p95_ms": 12.0, "error_rate": 0.0},
        {"p95_ms": 10.0, "error_rate": 0.0},
        max_p95_regression_pct=25.0,
        max_error_rate_regression_abs=0.01,
    )
    assert ok is True
    assert any("OK" in msg for msg in messages)


def test_compare_fails_on_p95_regression() -> None:
    ok, messages = compare(
        {"p95_ms": 16.0, "error_rate": 0.0},
        {"p95_ms": 10.0, "error_rate": 0.0},
        max_p95_regression_pct=20.0,
        max_error_rate_regression_abs=0.01,
    )
    assert ok is False
    assert any("p95 regression" in msg for msg in messages)


def test_compare_fails_on_error_regression() -> None:
    ok, messages = compare(
        {"p95_ms": 10.0, "error_rate": 0.03},
        {"p95_ms": 10.0, "error_rate": 0.0},
        max_p95_regression_pct=20.0,
        max_error_rate_regression_abs=0.01,
    )
    assert ok is False
    assert any("error-rate regression" in msg for msg in messages)
