import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI

from app.config import settings
from app.jobs.daily_ingest import run_daily_ingest

logging.basicConfig(
    level=settings.log_level,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "service": "price-ingestion", "message": "%(message)s"}',
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KrishiNiti Price Ingestion Service",
    version="2.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
)

scheduler = AsyncIOScheduler(timezone="UTC")
_executor = ThreadPoolExecutor(max_workers=2)
_backfill_jobs: dict[str, dict] = {}


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
    _executor.shutdown(wait=False)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "price-ingestion", "version": "2.0.0"}


@app.post("/api/v1/jobs/run-ingest", tags=["jobs"])
async def trigger_ingest() -> dict:
    """Manually trigger full ingestion job (all 9 sources)."""
    result = await run_daily_ingest()
    return {"status": "completed", "result": result}


@app.post("/api/v1/jobs/run-backfill-weather", tags=["jobs"])
async def trigger_weather_backfill(
    background_tasks: BackgroundTasks,
    start_year: int = 1984,
) -> dict:
    """
    Backfills Open-Meteo ERA5 historical weather for all 50 districts.
    Starts from start_year (default 1984 — ERA5 starts 1940 but 1984 is practical).
    Runs in background — takes 10-30 minutes for full 40yr backfill.
    Poll GET /api/v1/jobs/backfill-weather/{job_id} for status.
    """
    job_id = str(uuid.uuid4())
    _backfill_jobs[job_id] = {"status": "running", "progress": None, "error": None}

    def _run():
        from app.ingestion.open_meteo import fetch_historical_weather
        from app.jobs.daily_ingest import DATABASE_URL
        import psycopg2
        import psycopg2.extras

        WEATHER_INSERT_SQL = """
            INSERT INTO weather_data
                (observation_date, district, state, latitude, longitude,
                 temp_max_c, temp_min_c, temp_avg_c, precipitation_mm,
                 humidity_pct, wind_speed_ms, source, is_forecast)
            VALUES (%(observation_date)s, %(district)s, %(state)s, %(latitude)s, %(longitude)s,
                    %(temp_max_c)s, %(temp_min_c)s, %(temp_avg_c)s, %(precipitation_mm)s,
                    %(humidity_pct)s, %(wind_speed_ms)s, %(source)s, %(is_forecast)s)
            ON CONFLICT (observation_date, district, source, is_forecast) DO NOTHING
        """

        total_inserted = 0
        conn = None
        try:
            conn = psycopg2.connect(DATABASE_URL)
            start = date(start_year, 1, 1)
            end = date.today()

            # Fetch in 1-year chunks to avoid API limits
            from datetime import timedelta
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(date(chunk_start.year, 12, 31), end)
                try:
                    records = fetch_historical_weather(chunk_start, chunk_end)
                    if records:
                        with conn.cursor() as cur:
                            psycopg2.extras.execute_batch(cur, WEATHER_INSERT_SQL, records, page_size=500)
                        conn.commit()
                        total_inserted += len(records)
                    _backfill_jobs[job_id]["progress"] = f"{chunk_start.year} done — {total_inserted} rows total"
                    logger.info(f"Weather backfill {chunk_start.year}: {len(records) if records else 0} records")
                except Exception as e:
                    logger.warning(f"Weather backfill chunk {chunk_start.year} failed: {e}")

                chunk_start = date(chunk_start.year + 1, 1, 1)

            _backfill_jobs[job_id] = {
                "status": "completed",
                "progress": f"Done — {total_inserted} total rows inserted",
                "error": None,
            }
        except Exception as e:
            _backfill_jobs[job_id] = {"status": "failed", "progress": None, "error": str(e)}
            logger.error(f"Weather backfill job {job_id} failed: {e}")
        finally:
            if conn:
                conn.close()

    background_tasks.add_task(asyncio.get_event_loop().run_in_executor, _executor, _run)
    return {"status": "started", "job_id": job_id,
            "poll_url": f"/api/v1/jobs/backfill-weather/{job_id}"}


@app.get("/api/v1/jobs/backfill-weather/{job_id}", tags=["jobs"])
async def get_weather_backfill_status(job_id: str) -> dict:
    from fastapi import HTTPException
    job = _backfill_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Backfill job {job_id} not found")
    return {"job_id": job_id, **job}


@app.post("/api/v1/jobs/run-backfill-prices", tags=["jobs"])
async def trigger_price_backfill(background_tasks: BackgroundTasks) -> dict:
    """
    Seeds the DB with full historical price data:
    - DoF MRP history for UREA/DAP/MOP/SSP/NPK (2019-now)
    - PPAC diesel price history (2019-now)
    This unblocks SSP/NPK model training immediately.
    """
    job_id = str(uuid.uuid4())
    _backfill_jobs[job_id] = {"status": "running", "progress": None, "error": None}

    def _run():
        from app.ingestion.fert_nic_scraper import get_full_mrp_history
        from app.ingestion.ppac_scraper import get_full_diesel_history
        from app.jobs.daily_ingest import DATABASE_URL, PRICE_INSERT_SQL
        import psycopg2
        import psycopg2.extras

        total_inserted = 0
        conn = None
        try:
            conn = psycopg2.connect(DATABASE_URL)

            # Seed DoF MRP history
            mrp_records = get_full_mrp_history()
            _backfill_jobs[job_id]["progress"] = f"Seeding {len(mrp_records)} DoF MRP records..."
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, PRICE_INSERT_SQL, mrp_records, page_size=500)
            conn.commit()
            total_inserted += len(mrp_records)

            # Seed PPAC diesel history
            diesel_records = get_full_diesel_history()
            _backfill_jobs[job_id]["progress"] = f"Seeding {len(diesel_records)} PPAC diesel records..."
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, PRICE_INSERT_SQL, diesel_records, page_size=500)
            conn.commit()
            total_inserted += len(diesel_records)

            _backfill_jobs[job_id] = {
                "status": "completed",
                "progress": f"Done — {total_inserted} total rows inserted",
                "error": None,
            }
        except Exception as e:
            _backfill_jobs[job_id] = {"status": "failed", "progress": None, "error": str(e)}
            import logging
            logging.getLogger(__name__).error(f"Price backfill job {job_id} failed: {e}")
        finally:
            if conn:
                conn.close()

    background_tasks.add_task(asyncio.get_event_loop().run_in_executor, _executor, _run)
    return {"status": "started", "job_id": job_id,
            "poll_url": f"/api/v1/jobs/backfill-weather/{job_id}"}
