from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException


class ErrorCode(StrEnum):
    AUTH_INVALID_KEY = "AUTH_INVALID_KEY"
    AUTH_MISSING_KEY = "AUTH_MISSING_KEY"
    WEBHOOK_INVALID_SIGNATURE = "WEBHOOK_INVALID_SIGNATURE"
    WEBHOOK_DUPLICATE_DELIVERY = "WEBHOOK_DUPLICATE_DELIVERY"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    STORAGE_ERROR = "STORAGE_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


class AppHTTPException(HTTPException):
    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
