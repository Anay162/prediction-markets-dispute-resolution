"""
api/main.py

FastAPI application entry point.
Handles startup/shutdown, CORS, routers, and exception handlers.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import audit, contracts, health, reports

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup
    _configure_logging()

    from data.cache.redis_client import init_redis
    from data.database import init_db

    init_db(
        database_url=os.environ["DATABASE_URL"],
        pool_size=int(os.getenv("DATABASE_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "20")),
    )
    init_redis(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Build the LLM client and pipeline and stash on app.state
    # so routers can access it without recreating per request
    from core.pipeline import AuditPipeline
    from integrations.llm.client import LLMClient

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        primary_model=os.getenv("PRIMARY_MODEL", "claude-sonnet-4-20250514"),
    )
    app.state.llm = llm
    app.state.pipeline = AuditPipeline(
        llm_client=llm,
        db_session_factory=_get_session_factory(),
        opencorporates_api_key=os.getenv("OPENCORPORATES_API_KEY"),
    )

    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(dsn=sentry_dsn, integrations=[FastApiIntegration()])

    logger.info("Application startup complete")
    yield

    # Shutdown
    logger.info("Application shutting down")


app = FastAPI(
    title="Contract Auditor API",
    description="AI-powered adversarial audit tool for prediction market contracts",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — tighten origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Request timing middleware
# ------------------------------------------------------------------


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


# ------------------------------------------------------------------
# Global exception handlers
# ------------------------------------------------------------------


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=exc, path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. The error has been logged."},
    )


# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------

app.include_router(health.router, tags=["health"])
app.include_router(audit.router, prefix="/v1", tags=["audit"])
app.include_router(contracts.router, prefix="/v1", tags=["contracts"])
app.include_router(reports.router, prefix="/v1", tags=["reports"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_session_factory():
    from data.database import get_session

    return get_session


def _configure_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
    )
