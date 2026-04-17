"""
api/middleware.py

Custom middleware for the FastAPI application.

Responsibilities:
- Structured request/response logging with timing
- Normalises uncaught exceptions into consistent JSON error shapes
- Attaches a unique request ID to every request for log correlation
"""
from __future__ import annotations

import logging
import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with method, path, status code, and duration.
    Attaches a unique X-Request-ID header to every response.

    Skips logging for /health and /ready probes to avoid log noise.
    """

    SKIP_PATHS = frozenset({"/health", "/ready"})

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # Attach request ID to request state so route handlers can reference it
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception as exc:
            # Last-resort catch — FastAPI's exception handlers should fire first
            duration_ms = (time.monotonic() - start) * 1000
            if request.url.path not in self.SKIP_PATHS:
                logger.error(
                    "unhandled_exception",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    duration_ms=round(duration_ms, 1),
                    error=str(exc),
                )
            raise

        duration_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id

        if request.url.path not in self.SKIP_PATHS:
            log_fn = logger.warning if response.status_code >= 400 else logger.info
            log_fn(
                "request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(duration_ms, 1),
            )

        return response


class ErrorNormalisationMiddleware(BaseHTTPMiddleware):
    """
    Catches any exception that slips past FastAPI's exception handlers
    and returns a clean JSON response instead of a 500 HTML page.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            logger.error(
                "middleware_caught_error",
                path=request.url.path,
                error=str(exc),
                exc_info=True,
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
