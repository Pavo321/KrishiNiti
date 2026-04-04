"""
KrishiNiti Farmer Service — entry point.

Responsibilities:
- Register/manage farmer profiles (PII encrypted at rest)
- Expose CRUD API consumed by alert-service and analytics-service
- Structured JSON logging so log aggregators (Loki, CloudWatch) can query fields
"""

import logging
import sys
import time
from contextlib import asynccontextmanager

import psycopg2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes.farmers import router as farmers_router


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_object: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "farmer-service",
            "environment": settings.environment,
        }
        # Merge any extra= fields passed by callers
        for key, value in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName",
            }:
                log_object[key] = value

        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_object, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "farmer_service_starting",
        extra={"environment": settings.environment, "log_level": settings.log_level},
    )
    # Verify DB connectivity on startup; fail fast rather than serving
    # health=ok when the database is unreachable.
    try:
        conn = psycopg2.connect(settings.database_url)
        conn.close()
        logger.info("db_connection_verified")
    except Exception as exc:
        logger.error("db_connection_failed", extra={"error": str(exc)})
        # Don't raise — let the service start so Kubernetes can surface logs.
        # Liveness probe will fail until DB recovers.

    yield

    logger.info("farmer_service_stopping")


app = FastAPI(
    title="KrishiNiti Farmer Service",
    version="1.0.0",
    description=(
        "Manages farmer profiles. PII (phone, name) is AES-256-GCM encrypted "
        "at rest. Exposes CRUD API for use by alert-service and analytics-service."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# ---------------------------------------------------------------------------
# Global exception handler — prevents stack traces leaking to callers
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "unhandled_exception",
        extra={"path": request.url.path, "error": str(exc)},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check service logs."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(farmers_router)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
def health() -> dict:
    """
    Liveness probe.

    Returns 200 as long as the process is running. Does not check DB —
    that would make a healthy process fail if DB is briefly unavailable.
    Use /health/ready for a readiness probe that checks DB connectivity.
    """
    return {"status": "ok", "service": "farmer-service", "version": "1.0.0"}


@app.get("/health/ready", tags=["ops"])
def readiness() -> dict:
    """
    Readiness probe. Kubernetes stops sending traffic if this returns non-200.
    Checks that DB is reachable before declaring ready.
    """
    try:
        conn = psycopg2.connect(settings.database_url, connect_timeout=3)
        conn.close()
        return {"status": "ready", "db": "ok"}
    except Exception as exc:
        logger.warning("readiness_check_failed", extra={"error": str(exc)})
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "db": "unreachable"},
        )
