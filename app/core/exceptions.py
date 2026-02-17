"""Custom exception hierarchy for webhook bridge error handling.

This module defines typed exceptions used across request validation,
authentication, storage operations, and circuit-breaker behavior.
Each exception carries an HTTP status code and machine-readable error code
for consistent API responses.
"""

from __future__ import annotations


class WebhookError(Exception):
    """Base exception for API-facing webhook bridge errors.

    Attributes:
        message: Human-readable error message.
        error_code: Machine-readable error code used in JSON responses.
        status_code: HTTP status code for the response.
    """

    default_error_code = "webhook_error"
    default_status_code = 400

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.default_error_code
        self.status_code = status_code or self.default_status_code


class AuthenticationError(WebhookError):
    """Raised when authentication or authorization checks fail."""

    default_error_code = "AUTH_INVALID_KEY"
    default_status_code = 401


class ValidationError(WebhookError):
    """Raised when incoming input data is invalid."""

    default_error_code = "VALIDATION_ERROR"
    default_status_code = 400


class StorageError(WebhookError):
    """Raised when persistence/storage operations fail."""

    default_error_code = "STORAGE_ERROR"
    default_status_code = 503


class CircuitBreakerError(WebhookError):
    """Raised when circuit breaker rejects execution."""

    default_error_code = "CIRCUIT_BREAKER_OPEN"
    default_status_code = 503
