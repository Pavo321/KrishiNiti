import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import settings
from app.jobs.daily_ingest import run_daily_ingest

logging.basicConfig(
    level=settings.log_level,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "service": "price-ingestion", "message": "%(message)s"}',
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KrishiNiti Price Ingestion Service",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
)

scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup() -> None:
    # Daily ingestion at 2:00 AM IST = 20:30 UTC
    scheduler.add_job(
        run_daily_ingest,
        "cron",
        hour=settings.ingest_cron_hour_utc,
        minute=settings.ingest_cron_minute_utc,
        id="daily_price_ingest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Price ingestion scheduler started. Next run at 02:00 IST.")


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "price-ingestion"}


@app.post("/api/v1/jobs/run-ingest", tags=["jobs"])
async def trigger_ingest() -> dict:
    """Manually trigger the ingestion job (dev/testing use)."""
    result = await run_daily_ingest()
    return {"status": "completed", "result": result}
