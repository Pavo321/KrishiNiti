import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import settings
from app.jobs.load_weather import run_weather_load

logging.basicConfig(
    level=settings.log_level,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "service": "weather", "message": "%(message)s"}',
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KrishiNiti Weather Service",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
)

scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup() -> None:
    # Load NASA POWER files daily at 21:00 UTC (2:30 AM IST)
    scheduler.add_job(
        run_weather_load,
        "cron",
        hour=settings.load_cron_hour_utc,
        minute=settings.load_cron_minute_utc,
        id="daily_weather_load",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Weather scheduler started. Next load at "
        f"{settings.load_cron_hour_utc:02d}:{settings.load_cron_minute_utc:02d} UTC "
        f"(02:30 IST)."
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "weather"}


@app.post("/api/v1/jobs/load-weather", tags=["jobs"])
async def trigger_load() -> dict:
    """Manually trigger the NASA POWER file loader (dev/testing use)."""
    result = await run_weather_load()
    return {"status": "completed", "result": result}
