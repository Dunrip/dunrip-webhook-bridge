"""Circuit breaker pattern for Telegram API resilience."""

import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject fast
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """Circuit breaker for external service calls.
    
    - CLOSED: Normal operation, requests pass through
    - OPEN: After threshold failures, reject immediately  
    - HALF_OPEN: After timeout, allow one test request
    """
    
    def __init__(
        self,
        failure_threshold: int | None = None,
        timeout: int | None = None,
    ):
        self.failure_threshold = failure_threshold or settings.circuit_breaker_threshold
        self.timeout = timeout or settings.circuit_breaker_timeout
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        
    @property
    def state(self) -> CircuitState:
        return self._state
        
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state and emit metrics if available."""
        old_state = self._state
        if old_state != new_state:
            self._state = new_state
            # Emit metrics if prometheus client is available
            try:
                from prometheus_client import REGISTRY, Counter
                metric_name = "circuit_breaker_state_changes_total"
                # Check if metric already exists in registry
                if metric_name not in REGISTRY._names_to_collectors:
                    CIRCUIT_BREAKER_STATE = Counter(
                        metric_name,
                        "Circuit breaker state changes",
                        ["from_state", "to_state"]
                    )
                else:
                    CIRCUIT_BREAKER_STATE = REGISTRY._names_to_collectors[metric_name]
                CIRCUIT_BREAKER_STATE.labels(
                    from_state=old_state.value, to_state=new_state.value
                ).inc()
            except ImportError:
                pass  # Metrics not available during tests
        
    def _trip(self) -> None:
        """Trip the circuit to OPEN."""
        self._transition_to(CircuitState.OPEN)
        self._last_failure_time = time.time()
        logger.warning(
            "Circuit breaker TRIPPED to OPEN (threshold=%d)",
            self.failure_threshold
        )
        
    def _reset(self) -> None:
        """Reset to CLOSED."""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._last_failure_time = None
        logger.info("Circuit breaker RESET to CLOSED")
        
    def _try_transition_to_half_open(self) -> bool:
        """Check if we should try half-open state."""
        if self._state != CircuitState.OPEN:
            return False
            
        if self._last_failure_time is None:
            return False
            
        elapsed = time.time() - self._last_failure_time
        if elapsed >= self.timeout:
            self._transition_to(CircuitState.HALF_OPEN)
            logger.info("Circuit breaker transitioned to HALF_OPEN")
            return True
        return False
        
    def can_execute(self) -> bool:
        """Check if request should be allowed."""
        if self._state == CircuitState.CLOSED:
            return True
            
        if self._state == CircuitState.OPEN:
            if self._try_transition_to_half_open():
                return True
            return False
            
        return True  # HALF_OPEN
        
    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._reset()
        else:
            self._failure_count = max(0, self._failure_count - 1)
            
    def record_failure(self) -> bool:
        """Record a failed call. Returns True if circuit tripped."""
        self._failure_count += 1
        
        if self._state == CircuitState.HALF_OPEN:
            self._trip()
            return True
            
        if self._failure_count >= self.failure_threshold:
            self._trip()
            return True
            
        return False
        
    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap a function with circuit breaker."""
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            if not self.can_execute():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN (timeout={self.timeout}s)"
                )
                
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as exc:
                if self.record_failure():
                    logger.error("Circuit breaker tripped due to: %s", exc)
                raise
                
        return async_wrapper  # type: ignore[return-value]


class CircuitBreakerOpenError(RuntimeError):
    """Raised when circuit breaker is open."""
    pass


# Global circuit breaker instance for Telegram
telegram_circuit = CircuitBreaker()
