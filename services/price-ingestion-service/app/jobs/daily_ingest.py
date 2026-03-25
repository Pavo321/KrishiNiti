"""
Daily price ingestion job.
Runs at 2:00 AM IST. Idempotent — safe to run multiple times.
"""

import logging
import os
from datetime import date

import psycopg2
import psycopg2.extras

from app.ingestion.worldbank import fetch_latest_prices

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]


async def run_daily_ingest() -> dict:
    logger.info("Starting daily price ingestion job")
    results = {}

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        raise

    try:
        # World Bank prices
        wb_result = _ingest_worldbank(conn)
        results["worldbank"] = wb_result

    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(f"Daily ingestion complete: {results}")
    return results


def _ingest_worldbank(conn) -> dict:
    records = fetch_latest_prices()

    insert_sql = """
        INSERT INTO commodity_prices
            (price_date, commodity, price_inr, price_usd, unit,
             source, exchange_rate, raw_file_hash)
        VALUES (%(price_date)s, %(commodity)s, %(price_inr)s, %(price_usd)s,
                %(unit)s, %(source)s, %(exchange_rate)s, %(raw_file_hash)s)
        ON CONFLICT (price_date, commodity, source,
                     COALESCE(district, ''), COALESCE(mandi_name, ''))
        DO NOTHING
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, records, page_size=500)
        inserted = cur.rowcount

    conn.commit()
    logger.info(f"WorldBank: {len(records)} records processed, {inserted} new")
    return {"total": len(records), "inserted": inserted}
