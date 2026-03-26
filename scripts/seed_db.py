"""
Seeds TimescaleDB with real data from fetched raw files.
Run after fetch_worldbank_pinksheet.py and fetch_nasa_power.py.
Idempotent: skips records that already exist (uses UNIQUE constraint).
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://krishiniti_app:@localhost:5432/krishiniti",
)

RAW_DIR = Path("data/raw")

# Approximate USD → INR rate (update periodically from RBI)
# In production the price-ingestion-service fetches live rates from RBI API
DEFAULT_USD_TO_INR = 83.5


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def seed_worldbank_prices(conn) -> int:
    """Load World Bank Pink Sheet JSON files into commodity_prices."""
    files = sorted(Path("data/raw/fertilizer_prices").glob("worldbank_pinksheet_*.json"))
    if not files:
        print("No World Bank JSON files found. Run fetch_worldbank_pinksheet.py first.")
        return 0

    latest_file = files[-1]
    print(f"Loading {latest_file.name}...")

    with open(latest_file) as f:
        records = json.load(f)

    # USD → INR conversion (use rate from file date or default)
    # In production: fetch from RBI FBIL API
    usd_to_inr = DEFAULT_USD_TO_INR
    print(f"Using USD/INR rate: {usd_to_inr} (update from RBI FBIL for accuracy)")

    rows = [
        (
            r["price_date"],
            r["commodity"],
            round(r["price_usd"] * usd_to_inr * 50 / 1000, 2),  # USD/MT → INR/50kg bag
            r["price_usd"],
            "INR_PER_BAG",
            r["source"],
            usd_to_inr,
            r["raw_file_hash"],
        )
        for r in records
    ]

    insert_sql = """
        INSERT INTO commodity_prices
            (price_date, commodity, price_inr, price_usd, unit, source, exchange_rate, raw_file_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (price_date, commodity, source,
                     COALESCE(district, ''), COALESCE(mandi_name, ''))
        DO NOTHING
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=500)
        inserted = cur.rowcount

    conn.commit()
    print(f"  Inserted {len(rows)} rows ({inserted} new, {len(rows)-inserted} already existed)")
    return len(rows)


def seed_nasa_power_weather(conn) -> int:
    """Load NASA POWER JSON files into weather_data."""
    files = list(Path("data/raw/weather").glob("*_nasa_power_*.json"))
    if not files:
        print("No NASA POWER JSON files found. Run fetch_nasa_power.py first.")
        return 0

    total = 0
    for file_path in files:
        print(f"Loading {file_path.name}...")
        with open(file_path) as f:
            data = json.load(f)

        district = data["district"]
        lat = data["latitude"]
        lon = data["longitude"]
        params_data = data["data"]

        # Get all dates (from T2M parameter as reference)
        t2m = params_data.get("T2M", {})
        all_dates = sorted(t2m.keys())

        rows = []
        for date_str in all_dates:
            # NASA POWER date format: YYYYMMDD
            obs_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))

            def get_val(param: str) -> float | None:
                v = params_data.get(param, {}).get(date_str)
                return None if v is None or v == -999 else float(v)

            rows.append((
                obs_date,
                district,
                data.get("state", ""),
                lat,
                lon,
                get_val("T2M_MAX"),
                get_val("T2M_MIN"),
                get_val("T2M"),
                get_val("PRECTOTCORR"),
                get_val("RH2M"),
                get_val("WS10M"),
                "NASA_POWER",
                False,
            ))

        insert_sql = """
            INSERT INTO weather_data
                (observation_date, district, state, latitude, longitude,
                 temp_max_c, temp_min_c, temp_avg_c,
                 precipitation_mm, humidity_pct, wind_speed_ms,
                 source, is_forecast)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (observation_date, district, source, is_forecast)
            DO NOTHING
        """

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=500)

        conn.commit()
        print(f"  {district}: {len(rows)} daily records")
        total += len(rows)

    return total


def verify_seed(conn) -> bool:
    """Quick sanity check on seeded data."""
    checks_passed = True

    with conn.cursor() as cur:
        # Check commodity prices
        cur.execute("""
            SELECT commodity, COUNT(*), MIN(price_date), MAX(price_date),
                   ROUND(AVG(price_inr)::numeric, 2)
            FROM commodity_prices
            GROUP BY commodity
            ORDER BY commodity
        """)
        rows = cur.fetchall()
        print("\nCommodity Prices Summary:")
        for row in rows:
            print(f"  {row[0]}: {row[1]} records, {row[2]} to {row[3]}, avg ₹{row[4]}/bag")
            if row[1] < 100:
                print(f"  WARNING: Only {row[1]} records for {row[0]}. Expected 500+.")
                checks_passed = False

        # Check weather data
        cur.execute("""
            SELECT district, COUNT(*), MIN(observation_date), MAX(observation_date)
            FROM weather_data
            GROUP BY district
            ORDER BY district
        """)
        rows = cur.fetchall()
        print("\nWeather Data Summary:")
        for row in rows:
            print(f"  {row[0]}: {row[1]} daily records, {row[2]} to {row[3]}")
            if row[1] < 1000:
                print(f"  WARNING: Only {row[1]} records for {row[0]}. Expected 3000+.")
                checks_passed = False

    return checks_passed


def main() -> None:
    print(f"Connecting to {DATABASE_URL.split('@')[1]}...")  # hide credentials

    try:
        conn = get_connection()
    except Exception as e:
        print(f"Cannot connect to database: {e}")
        print("Start database with: docker-compose up -d postgres")
        sys.exit(1)

    print("Connected.\n")

    price_count = seed_worldbank_prices(conn)
    weather_count = seed_nasa_power_weather(conn)

    print(f"\nSeeded {price_count} price records and {weather_count} weather records.")

    print("\nRunning verification...")
    passed = verify_seed(conn)

    conn.close()

    if passed:
        print("\nAll checks passed. Data is ready for ML pipeline.")
    else:
        print("\nSome checks failed. Review warnings above before running models.")
        sys.exit(1)


if __name__ == "__main__":
    main()
