"""
KrishiNiti Alert Service

Responsibilities:
- Receive WhatsApp delivery receipts and farmer replies via webhook
- Expose alert delivery statistics and recent alert log
- (Future) Listen on Redis channel 'forecasts:ready' and dispatch WhatsApp alerts

Startup contract: must bind and respond to /health before any other work.
"""

import logging
import logging.config
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes.alerts import router as alerts_router


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import time

        payload: dict = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "service": "alert",
            "message": record.getMessage(),
        }

        # Extra fields added via logger.info("msg", extra={...})
        skip = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in skip:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Alert service ready. Listening for forecasts:ready events on Redis.")

    if not settings.whatsapp_api_token:
        logger.warning(
            "WHATSAPP_API_TOKEN is not set. "
            "Redis pub/sub listener and outbound WhatsApp dispatch are disabled. "
            "Webhook reception and DB reads remain fully operational."
        )

    if not settings.whatsapp_app_secret:
        logger.warning(
            "WHATSAPP_APP_SECRET is not set. "
            "Incoming webhook signature verification will reject all POST requests."
        )

    yield

    # Shutdown
    logger.info("Alert service shutting down.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KrishiNiti Alert Service",
    description=(
        "Dispatches WhatsApp price-timing alerts to farmers in 10 Indian languages. "
        "Receives delivery receipts and farmer replies via Meta webhook."
    ),
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    """
    Liveness probe. Returns 200 as long as the process is alive.
    Does NOT check DB or Redis — those are readiness concerns.
    """
    return JSONResponse({"status": "ok", "service": "alert"})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(alerts_router)
