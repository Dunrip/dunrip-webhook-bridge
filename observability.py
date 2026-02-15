from __future__ import annotations

import contextvars
import logging
from uuid import uuid4

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_ctx.get()
        return True


def new_request_id() -> str:
    return str(uuid4())


def get_request_id() -> str:
    return request_id_ctx.get()
