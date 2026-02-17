from app.services.reliability import backoff_with_jitter, classify_failure


def test_retry_classification_http() -> None:
    assert classify_failure(status_code=503).category == "5xx"
    assert classify_failure(status_code=429).category == "4xx"
    assert classify_failure(status_code=429).should_retry is False


def test_retry_classification_timeout() -> None:
    class TimeoutErr(Exception):
        pass

    decision = classify_failure(error=TimeoutErr("request timeout"))
    assert decision.category == "timeout"
    assert decision.should_retry is True


def test_backoff_increases_and_jitters() -> None:
    one = backoff_with_jitter(1, base_seconds=1.0, max_seconds=60.0, jitter_ratio=0.0)
    three = backoff_with_jitter(3, base_seconds=1.0, max_seconds=60.0, jitter_ratio=0.0)
    assert one == 1.0
    assert three == 4.0
