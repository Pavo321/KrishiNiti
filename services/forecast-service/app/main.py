import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException

from app.jobs.daily_forecast import run_daily_forecast
from app.evaluation.backtester import run_backtest

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "service": "forecast", "message": "%(message)s"}',
)
logger = logging.getLogger(__name__)

app = FastAPI(title="KrishiNiti Forecast Service", version="2.0.0")

scheduler = AsyncIOScheduler(timezone="UTC")
_executor = ThreadPoolExecutor(max_workers=2)

# In-memory backtest job tracker (survives only the process lifetime — good enough)
_backtest_jobs: dict[str, dict] = {}


@app.on_event("startup")
async def startup() -> None:
    # Daily forecast at 3:00 AM IST = 21:30 UTC
    scheduler.add_job(
        run_daily_forecast,
        "cron",
        hour=21,
        minute=30,
        id="daily_forecast",
        replace_existing=True,
    )
    # Daily accuracy evaluation at 4:00 AM IST = 22:30 UTC
    scheduler.add_job(
        _nightly_accuracy_eval,
        "cron",
        hour=22,
        minute=30,
        id="nightly_accuracy",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Forecast scheduler started. Forecast: 03:00 IST | Accuracy: 04:00 IST")


async def _nightly_accuracy_eval() -> None:
    """Calls analytics-service to evaluate expired forecasts and recompute weights."""
    import httpx
    analytics_url = os.environ.get("ANALYTICS_SERVICE_URL", "http://analytics-service:8000")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            await client.post(f"{analytics_url}/api/v1/accuracy/evaluate")
            await client.post(f"{analytics_url}/api/v1/accuracy/compute-weights")
        logger.info("Nightly accuracy evaluation completed")
    except Exception as e:
        logger.warning(f"Nightly accuracy eval failed: {e}")


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown()
    _executor.shutdown(wait=False)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "forecast", "version": "2.0.0"}


@app.post("/api/v1/jobs/run-forecast", tags=["jobs"])
async def trigger_forecast() -> dict:
    """Manually trigger the forecast job (Prophet + XGBoost + LSTM ensemble)."""
    result = await run_daily_forecast()
    return {"status": "completed", "result": result}


@app.post("/api/v1/jobs/run-backtest", tags=["jobs"])
async def trigger_backtest(
    background_tasks: BackgroundTasks,
    commodities: list[str] | None = None,
) -> dict:
    """
    Starts walk-forward backtest in background. Returns a job_id immediately.
    Poll GET /api/v1/jobs/backtest/{job_id} for status and results.
    Takes 5-15 minutes — runs async so the HTTP request doesn't time out.
    """
    job_id = str(uuid.uuid4())
    _backtest_jobs[job_id] = {"status": "running", "results": None, "error": None}

    def _run():
        try:
            results = run_backtest(commodities)
            _backtest_jobs[job_id] = {"status": "completed", "results": results, "error": None}
            logger.info(f"Backtest job {job_id} completed")
        except Exception as e:
            _backtest_jobs[job_id] = {"status": "failed", "results": None, "error": str(e)}
            logger.error(f"Backtest job {job_id} failed: {e}")

    background_tasks.add_task(asyncio.get_event_loop().run_in_executor, _executor, _run)
    return {"status": "started", "job_id": job_id,
            "poll_url": f"/api/v1/jobs/backtest/{job_id}"}


@app.get("/api/v1/jobs/backtest/{job_id}", tags=["jobs"])
async def get_backtest_status(job_id: str) -> dict:
    """Poll backtest job status. Returns results when completed."""
    job = _backtest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Backtest job {job_id} not found")
    return {"job_id": job_id, **job}
