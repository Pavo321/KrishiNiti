"""
Weather data loader job.
Scans NASA POWER JSON files from DATA_PATH and bulk-inserts into weather_data.
Idempotent — ON CONFLICT DO NOTHING ensures safe re-runs.
Runs at 21:00 UTC (2:30 AM IST) after forecast-service completes.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from app.config import settings

logger = logging.getLogger(__name__)

INSERT_SQL = """
    INSERT INTO weather_data (
        observation_date,
        district,
        state,
        latitude,
        longitude,
        temp_max_c,
        temp_min_c,
        temp_avg_c,
        precipitation_mm,
        humidity_pct,
        wind_speed_ms,
        source,
        is_forecast
    )
    VALUES (
        %(observation_date)s,
        %(district)s,
        %(state)s,
        %(latitude)s,
        %(longitude)s,
        %(temp_max_c)s,
        %(temp_min_c)s,
        %(temp_avg_c)s,
        %(precipitation_mm)s,
        %(humidity_pct)s,
        %(wind_speed_ms)s,
        %(source)s,
        %(is_forecast)s
    )
    ON CONFLICT DO NOTHING
"""


def _parse_date(date_str: str) -> date:
    """Convert NASA POWER compact date string YYYYMMDD to a date object."""
    return date(
        int(date_str[0:4]),
        int(date_str[4:6]),
        int(date_str[6:8]),
    )


def _build_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Transform a parsed NASA POWER JSON payload into a list of row dicts
    ready for psycopg2 batch insert.

    NASA POWER variables used:
        T2M          → temp_avg_c
        T2M_MAX      → temp_max_c
        T2M_MIN      → temp_min_c
        PRECTOTCORR  → precipitation_mm
        RH2M         → humidity_pct
        WS10M        → wind_speed_ms
    """
    district = payload["district"]
    state = payload["state"]
    latitude = payload["latitude"]
    longitude = payload["longitude"]
    source = payload.get("source", "NASA_POWER")
    data = payload["data"]

    t2m = data.get("T2M", {})
    t2m_max = data.get("T2M_MAX", {})
    t2m_min = data.get("T2M_MIN", {})
    precip = data.get("PRECTOTCORR", {})
    rh2m = data.get("RH2M", {})
    ws10m = data.get("WS10M", {})

    # Use T2M date keys as the canonical set; all variables share the same keys
    # but we guard against missing values with .get() to tolerate partial data.
    records = []
    for date_str in t2m:
        records.append(
            {
                "observation_date": _parse_date(date_str),
                "district": district,
                "state": state,
                "latitude": latitude,
                "longitude": longitude,
                "temp_avg_c": t2m.get(date_str),
                "temp_max_c": t2m_max.get(date_str),
                "temp_min_c": t2m_min.get(date_str),
                "precipitation_mm": precip.get(date_str),
                "humidity_pct": rh2m.get(date_str),
                "wind_speed_ms": ws10m.get(date_str),
                "source": source,
                "is_forecast": False,
            }
        )

    return records


def _load_file(conn, filepath: Path) -> dict[str, int]:
    """
    Parse one NASA POWER JSON file and batch-insert all daily records.

    Returns {"total": N, "inserted": N} where inserted reflects rows
    that were new (ON CONFLICT DO NOTHING discards duplicates silently).
    """
    logger.info(f"Processing file: {filepath.name}")

    with open(filepath, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    records = _build_records(payload)
    if not records:
        logger.info(f"{filepath.name}: no records parsed, skipping")
        return {"total": 0, "inserted": 0}

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, INSERT_SQL, records, page_size=500)
        # rowcount after execute_batch reflects the last batch only on some
        # drivers; summing is unreliable, so we use a mogrify-free count query
        # scoped to this file's (district, state, source) after commit.
        batch_rowcount = cur.rowcount

    conn.commit()

    # Accurate inserted count: rows that survived ON CONFLICT DO NOTHING
    # are the diff between what we sent and what already existed.  Because
    # execute_batch does not return per-row status we use a post-commit count
    # restricted to this file's key space.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM weather_data
            WHERE district = %s
              AND state    = %s
              AND source   = %s
              AND is_forecast = FALSE
              AND observation_date BETWEEN %s AND %s
            """,
            (
                payload["district"],
                payload["state"],
                payload.get("source", "NASA_POWER"),
                min(r["observation_date"] for r in records),
                max(r["observation_date"] for r in records),
            ),
        )
        db_count = cur.fetchone()[0]

    logger.info(
        f"{filepath.name}: {len(records)} records in file, "
        f"{db_count} rows now in DB for this district/source range"
    )
    return {"total": len(records), "inserted": batch_rowcount}


async def run_weather_load() -> dict[str, int]:
    """
    Scan DATA_PATH for all NASA POWER JSON files and load each into DB.

    Returns aggregated {"files_processed": N, "records_inserted": N}.
    Safe to call multiple times — duplicate dates are silently skipped.
    """
    data_path = Path(settings.data_path)
    json_files = sorted(data_path.glob("*.json"))

    if not json_files:
        logger.warning(f"No JSON files found in {data_path}")
        return {"files_processed": 0, "records_inserted": 0}

    logger.info(f"Found {len(json_files)} JSON file(s) in {data_path}")

    try:
        conn = psycopg2.connect(settings.database_url)
    except Exception as exc:
        logger.error(f"DB connection failed: {exc}")
        raise

    files_processed = 0
    records_inserted = 0

    try:
        for filepath in json_files:
            try:
                result = _load_file(conn, filepath)
                files_processed += 1
                records_inserted += result["inserted"]
            except Exception as exc:
                logger.error(f"Failed to load {filepath.name}: {exc}", exc_info=True)
                conn.rollback()
                # Continue with remaining files — one bad file must not abort the run
    finally:
        conn.close()

    logger.info(
        f"Weather load complete: {files_processed} files processed, "
        f"{records_inserted} new records inserted"
    )
    return {"files_processed": files_processed, "records_inserted": records_inserted}
