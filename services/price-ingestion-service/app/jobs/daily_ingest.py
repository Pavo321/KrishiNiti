"""
Daily price ingestion job.
Runs at 2:00 AM IST. Idempotent — safe to run multiple times.

v2: Ingests from 9 sources:
  - World Bank Pink Sheet (monthly global)
  - Agmarknet (daily district mandi prices)
  - eNAM (real cleared transaction prices)
  - fert.nic.in (retail MRP)
  - Open-Meteo (weather — replaces NASA POWER)
  - NCDEX futures settlement
  - PPAC diesel prices
  - PM-KISAN tranche events
  - RBI seasonal signals
"""

import logging
import os
from datetime import date

import psycopg2
import psycopg2.extras

from app.ingestion.agmarknet import fetch_mandi_prices
from app.ingestion.enam import fetch_enam_prices
from app.ingestion.fert_nic_scraper import fetch_retail_prices
from app.ingestion.ncdex_scraper import fetch_settlement_prices
from app.ingestion.open_meteo import fetch_historical_weather, fetch_forecast_weather
from app.ingestion.pmkisan_scraper import fetch_pmkisan_events
from app.ingestion.ppac_scraper import fetch_diesel_prices
from app.ingestion.rbi_dbie import fetch_rbi_indicators, fetch_rbi_historical_credit
from app.ingestion.worldbank import fetch_latest_prices

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

# Commodity prices insert SQL (shared across price sources)
PRICE_INSERT_SQL = """
    INSERT INTO commodity_prices
        (price_date, commodity, price_inr, price_usd, unit,
         source, state, district, mandi_name, exchange_rate, raw_file_hash)
    VALUES (%(price_date)s, %(commodity)s, %(price_inr)s, %(price_usd)s,
            %(unit)s, %(source)s, %(state)s, %(district)s, %(mandi_name)s,
            %(exchange_rate)s, %(raw_file_hash)s)
    ON CONFLICT (price_date, commodity, source,
                 COALESCE(district, ''), COALESCE(mandi_name, ''))
    DO NOTHING
"""

# Market events insert SQL
EVENTS_INSERT_SQL = """
    INSERT INTO market_events
        (event_date, event_type, commodity, description, source, price_inr, contract, expiry_date)
    VALUES (%(event_date)s, %(event_type)s, %(commodity)s, %(description)s,
            %(source)s, %(price_inr)s, %(contract)s, %(expiry_date)s)
    ON CONFLICT (event_date, event_type, COALESCE(commodity, ''), COALESCE(contract, ''))
    DO NOTHING
"""

# Weather insert SQL
WEATHER_INSERT_SQL = """
    INSERT INTO weather_data
        (observation_date, district, state, latitude, longitude,
         temp_max_c, temp_min_c, temp_avg_c, precipitation_mm,
         humidity_pct, wind_speed_ms, source, is_forecast)
    VALUES (%(observation_date)s, %(district)s, %(state)s, %(latitude)s, %(longitude)s,
            %(temp_max_c)s, %(temp_min_c)s, %(temp_avg_c)s, %(precipitation_mm)s,
            %(humidity_pct)s, %(wind_speed_ms)s, %(source)s, %(is_forecast)s)
    ON CONFLICT (observation_date, district, source, is_forecast)
    DO NOTHING
"""


async def run_daily_ingest() -> dict:
    logger.info("Starting daily price ingestion job v2")
    results = {}

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        raise

    try:
        # === PRICE SOURCES ===
        results["worldbank"]  = _ingest_prices(conn, fetch_latest_prices, "worldbank")
        results["agmarknet"]  = _ingest_agmarknet(conn)
        results["enam"]       = _ingest_prices_simple(conn, fetch_enam_prices, "enam")
        results["fert_nic"]   = _ingest_prices_simple(conn, fetch_retail_prices, "fert_nic")
        results["ppac"]       = _ingest_prices_simple(conn, fetch_diesel_prices, "ppac")

        # === MARKET EVENTS ===
        results["ncdex"]      = _ingest_market_events(conn, fetch_settlement_prices, "ncdex")
        results["pmkisan"]    = _ingest_market_events(conn, fetch_pmkisan_events, "pmkisan")
        results["rbi"]        = _ingest_market_events(conn, fetch_rbi_indicators, "rbi")

        # === WEATHER ===
        results["weather"]    = _ingest_weather(conn)

    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(f"Daily ingestion v2 complete: {results}")
    return results


def _ingest_agmarknet(conn) -> dict:
    records = fetch_mandi_prices()
    if not records:
        return {"total": 0, "inserted": 0}

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, PRICE_INSERT_SQL, records, page_size=500)
        inserted = cur.rowcount

    conn.commit()
    logger.info(f"Agmarknet: {len(records)} records processed, {inserted} new")
    return {"total": len(records), "inserted": inserted}


def _ingest_prices(conn, fetch_fn, label: str) -> dict:
    """Ingest from a fetch function that returns full price dicts (worldbank format)."""
    try:
        records = fetch_fn()
    except Exception as e:
        logger.error(f"{label}: fetch failed: {e}")
        return {"total": 0, "inserted": 0, "error": str(e)}

    if not records:
        return {"total": 0, "inserted": 0}

    # Ensure all required keys exist
    normalized = [_normalize_price_record(r) for r in records]

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, PRICE_INSERT_SQL, normalized, page_size=500)
        inserted = cur.rowcount

    conn.commit()
    logger.info(f"{label}: {len(records)} records processed, {inserted} new")
    return {"total": len(records), "inserted": inserted}


def _ingest_prices_simple(conn, fetch_fn, label: str) -> dict:
    """Same as _ingest_prices but catches and logs errors gracefully."""
    try:
        return _ingest_prices(conn, fetch_fn, label)
    except Exception as e:
        logger.warning(f"{label}: ingest failed (non-critical): {e}")
        return {"total": 0, "inserted": 0, "error": str(e)}


def _ingest_market_events(conn, fetch_fn, label: str) -> dict:
    """Ingest market events (PM-KISAN tranches, NCDEX futures, RBI signals)."""
    try:
        events = fetch_fn()
    except Exception as e:
        logger.warning(f"{label}: fetch failed: {e}")
        return {"total": 0, "inserted": 0, "error": str(e)}

    if not events:
        return {"total": 0, "inserted": 0}

    normalized = [_normalize_event_record(e) for e in events]

    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, EVENTS_INSERT_SQL, normalized, page_size=500)
            inserted = cur.rowcount
        conn.commit()
    except Exception as e:
        logger.warning(f"{label}: DB insert failed: {e}")
        conn.rollback()
        return {"total": len(events), "inserted": 0, "error": str(e)}

    logger.info(f"{label}: {len(events)} events processed, {inserted} new")
    return {"total": len(events), "inserted": inserted}


def _ingest_weather(conn) -> dict:
    """Fetch and insert Open-Meteo weather data."""
    try:
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        records = fetch_historical_weather(yesterday, yesterday)
        forecast_records = fetch_forecast_weather()
        all_records = records + forecast_records
    except Exception as e:
        logger.warning(f"weather: fetch failed: {e}")
        return {"total": 0, "inserted": 0, "error": str(e)}

    if not all_records:
        return {"total": 0, "inserted": 0}

    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, WEATHER_INSERT_SQL, all_records, page_size=500)
            inserted = cur.rowcount
        conn.commit()
    except Exception as e:
        logger.warning(f"weather: DB insert failed: {e}")
        conn.rollback()
        return {"total": len(all_records), "inserted": 0, "error": str(e)}

    logger.info(f"weather (Open-Meteo): {len(all_records)} records, {inserted} new")
    return {"total": len(all_records), "inserted": inserted}


def _normalize_price_record(r: dict) -> dict:
    return {
        "price_date": r.get("price_date"),
        "commodity": r.get("commodity"),
        "price_inr": r.get("price_inr"),
        "price_usd": r.get("price_usd"),
        "unit": r.get("unit", "INR_PER_BAG"),
        "source": r.get("source"),
        "state": r.get("state"),
        "district": r.get("district"),
        "mandi_name": r.get("mandi_name"),
        "exchange_rate": r.get("exchange_rate"),
        "raw_file_hash": r.get("raw_file_hash"),
    }


def _normalize_event_record(e: dict) -> dict:
    return {
        "event_date": e.get("event_date"),
        "event_type": e.get("event_type"),
        "commodity": e.get("commodity"),
        "description": e.get("description"),
        "source": e.get("source"),
        "price_inr": e.get("price_inr"),
        "contract": e.get("contract"),
        "expiry_date": e.get("expiry_date"),
    }
