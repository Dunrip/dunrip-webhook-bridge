import time

import pytest

from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


def test_circuit_starts_closed():
    """Circuit breaker starts in CLOSED state."""
    cb = CircuitBreaker(failure_threshold=3, timeout=1)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute()


def test_circuit_opens_after_threshold():
    """Circuit opens after failure threshold is reached."""
    cb = CircuitBreaker(failure_threshold=3, timeout=60)
    
    # Record 3 failures
    cb.record_failure()
    cb.record_failure()
    tripped = cb.record_failure()
    
    assert tripped is True
    assert cb.state == CircuitState.OPEN
    assert not cb.can_execute()


def test_circuit_half_open_after_timeout():
    """Circuit transitions to HALF_OPEN after timeout."""
    cb = CircuitBreaker(failure_threshold=2, timeout=0.1)
    
    # Trip the circuit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    
    # Wait for timeout
    time.sleep(0.15)
    
    # Should now allow one request
    assert cb.can_execute()
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_closes_on_success_in_half_open():
    """Circuit closes when request succeeds in HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout=0.1)
    
    # Trip and transition to half-open
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    cb.can_execute()  # Transition to HALF_OPEN
    
    assert cb.state == CircuitState.HALF_OPEN
    
    # Success should close it
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_circuit_reopens_on_failure_in_half_open():
    """Circuit reopens when request fails in HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout=0.1)
    
    # Trip and transition to half-open
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    cb.can_execute()  # Transition to HALF_OPEN
    
    # Failure should trip again
    tripped = cb.record_failure()
    assert tripped is True
    assert cb.state == CircuitState.OPEN


def test_circuit_open_raises_error():
    """Circuit breaker raises error when open and called as decorator."""
    cb = CircuitBreaker(failure_threshold=1, timeout=60)
    
    @cb
    async def failing_func():
        raise RuntimeError("boom")
    
    # Trip it
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    
    import asyncio
    with pytest.raises(CircuitBreakerOpenError):
        asyncio.run(failing_func())


def test_circuit_decorator_records_success():
    """Decorator records success on successful call."""
    cb = CircuitBreaker(failure_threshold=3, timeout=60)
    call_count = 0
    
    @cb
    async def success_func():
        nonlocal call_count
        call_count += 1
        return "success"
    
    import asyncio
    result = asyncio.run(success_func())
    
    assert result == "success"
    assert call_count == 1
    assert cb.state == CircuitState.CLOSED
