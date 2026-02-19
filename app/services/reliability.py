from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RetryDecision:
    category: str
    should_retry: bool
    reason_code: str


def classify_failure(*, status_code: int | None = None, error: Exception | None = None) -> RetryDecision:
    if error is not None:
        name = error.__class__.__name__.lower()
        msg = str(error).lower()
        if "timeout" in name or "timeout" in msg:
            return RetryDecision("timeout", True, "timeout")
        if any(token in name for token in ("connect", "network", "socket")) or "network" in msg:
            return RetryDecision("network", True, "network_error")
    if status_code is None:
        return RetryDecision("unknown", True, "unknown_error")
    if 500 <= status_code <= 599:
        return RetryDecision("5xx", True, f"http_{status_code}")
    if 400 <= status_code <= 499:
        return RetryDecision("4xx", False, f"http_{status_code}")
    return RetryDecision("ok", False, "success")


def backoff_with_jitter(
    attempt: int, *, base_seconds: float = 1.0, max_seconds: float = 60.0, jitter_ratio: float = 0.2
) -> float:
    raw = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    spread = raw * jitter_ratio
    return max(0.0, raw + random.uniform(-spread, spread))


def payload_hash(payload: bytes | str | dict[str, Any]) -> str:
    if isinstance(payload, dict):
        body = str(sorted(payload.items())).encode("utf-8")
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload
    return hashlib.sha256(body).hexdigest()


def now_ts() -> float:
    return time.time()
