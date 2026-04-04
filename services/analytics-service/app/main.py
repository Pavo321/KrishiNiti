import logging
import logging.config

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import settings
from app.routes.accuracy import evaluate_pending_forecasts, router as accuracy_router

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
_LOG_FORMAT = (
    '{"time": "%(asctime)s", "level": "%(levelname)s",'
    ' "service": "analytics", "message": "%(message)s"}'
)
logging.basicConfig(level=settings.log_level.upper(), format=_LOG_FORMAT)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="KrishiNiti Analytics Service",
    version="1.0.0",
    description="Model accuracy tracking and forecast evaluation for KrishiNiti.",
)

app.include_router(accuracy_router, prefix="")

# ---------------------------------------------------------------------------
# Scheduler — daily evaluation at 22:00 UTC (3:30 AM IST)
# ---------------------------------------------------------------------------
scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup() -> None:
    scheduler.add_job(
        _run_evaluate_job,
        "cron",
        hour=22,
        minute=0,
        id="daily_evaluate",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Analytics scheduler started. Evaluation job runs daily at 22:00 UTC.")


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown()
    logger.info("Analytics scheduler stopped.")


def _run_evaluate_job() -> None:
    """Synchronous wrapper called by APScheduler."""
    try:
        result = evaluate_pending_forecasts()
        logger.info(
            "Scheduled evaluation complete: evaluated=%d correct=%d accuracy_pct=%.2f",
            result.evaluated,
            result.correct,
            result.accuracy_pct,
        )
    except Exception as exc:
        logger.error("Scheduled evaluation failed: %s", exc)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "analytics", "environment": settings.environment}


# ---------------------------------------------------------------------------
# Manual trigger (useful for dev / backfill)
# ---------------------------------------------------------------------------
@app.post("/api/v1/jobs/run-evaluate", tags=["jobs"])
def trigger_evaluate() -> dict:
    """Manually trigger the forecast evaluation job."""
    result = evaluate_pending_forecasts()
    return {"status": "completed", "result": result.model_dump()}
