"""Vercel serverless entrypoint for FastAPI app."""

import sys
import traceback

try:
    from app.main import app
    _startup_error = None
except Exception as e:
    _startup_error = traceback.format_exc()

    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()

    @app.get("/{path:path}")
    @app.post("/{path:path}")
    async def error_handler(path: str = "") -> PlainTextResponse:
        return PlainTextResponse(
            content=f"Startup error:\n\n{_startup_error}\n\nPython: {sys.version}",
            status_code=500,
        )
