"""
Fetches daily fertilizer prices from Agmarknet via data.gov.in API.
Covers 10 priority districts across major agricultural states.
Idempotent — safe to run multiple times.
"""

import logging
from datetime import date, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"

# Agmarknet commodity name → our internal code
COMMODITY_MAP = {
    "urea": "UREA",
    "dap": "DAP",
    "di-ammonium phosphate": "DAP",
    "di ammonium phosphate": "DAP",
    "mop": "MOP",
    "muriate of potash": "MOP",
    "potassium chloride": "MOP",
    "ssp": "SSP",
    "single super phosphate": "SSP",
    "superphosphate": "SSP",
    "npk 10:26:26": "NPK_102626",
    "npk10:26:26": "NPK_102626",
    "10-26-26": "NPK_102626",
    "npk 12:32:16": "NPK_123216",
    "12-32-16": "NPK_123216",
    "complex fertilizer": "NPK_102626",   # most common complex on Agmarknet
}

# 10 priority districts — all have matching weather data in DB
DISTRICTS = [
    ("Punjab", "Ludhiana"),
    ("Gujarat", "Ahmedabad"),
    ("Bihar", "Patna"),
    ("Maharashtra", "Nagpur"),
    ("Telangana", "Hyderabad"),
    ("Uttar Pradesh", "Lucknow"),
    ("Rajasthan", "Jaipur"),
    ("Karnataka", "Bangalore"),
    ("Madhya Pradesh", "Bhopal"),
    ("Tamil Nadu", "Chennai"),
]

# Backfill start — enough for Prophet training + backtesting
BACKFILL_FROM = date(2022, 1, 1)


def fetch_mandi_prices(from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    """
    Fetches mandi prices for all priority districts.
    - First run (no dates): backfills from 2022-01-01 to today.
    - Daily run: fetches yesterday only.
    Returns list of records matching commodity_prices schema.
    """
    if not settings.data_gov_api_key:
        logger.warning("DATA_GOV_API_KEY not set — skipping Agmarknet ingestion")
        return []

    if from_date is None:
        from_date = BACKFILL_FROM
    if to_date is None:
        to_date = date.today() - timedelta(days=1)

    logger.info(f"Fetching Agmarknet prices {from_date} → {to_date} for {len(DISTRICTS)} districts")

    all_records: list[dict] = []

    with httpx.Client(timeout=60) as client:
        for state, district in DISTRICTS:
            try:
                records = _fetch_district(client, state, district, from_date, to_date)
                all_records.extend(records)
                logger.info(f"{state}/{district}: {len(records)} records")
            except Exception as e:
                logger.warning(f"{state}/{district}: fetch failed — {e}")
                continue

    logger.info(f"Agmarknet total: {len(all_records)} records fetched")
    return all_records


def _fetch_district(
    client: httpx.Client,
    state: str,
    district: str,
    from_date: date,
    to_date: date,
) -> list[dict]:
    records: list[dict] = []
    offset = 0
    limit = 500

    while True:
        params = {
            "api-key": settings.data_gov_api_key,
            "format": "json",
            "limit": limit,
            "offset": offset,
            "filters[State]": state,
            "filters[District]": district,
            "filters[Arrival_Date]": f"{from_date.strftime('%d/%m/%Y')}:{to_date.strftime('%d/%m/%Y')}",
        }

        resp = client.get(API_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()

        records_raw = payload.get("records", [])
        if not records_raw:
            break

        for row in records_raw:
            record = _parse_record(row)
            if record:
                records.append(record)

        # If fewer than limit returned, we've reached the end
        if len(records_raw) < limit:
            break

        offset += limit

    return records


def _parse_record(row: dict) -> dict | None:
    commodity_raw = (row.get("Commodity") or row.get("commodity") or "").strip()
    commodity = _map_commodity(commodity_raw)
    if commodity is None:
        return None

    price_str = row.get("Modal_Price") or row.get("modal_price") or ""
    try:
        price_inr = float(str(price_str).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

    if price_inr <= 0:
        return None

    arrival_date = _parse_date(row.get("Arrival_Date") or row.get("arrival_date") or "")
    if arrival_date is None:
        return None

    return {
        "price_date": arrival_date,
        "commodity": commodity,
        "price_inr": price_inr,
        "price_usd": None,
        "unit": "INR_PER_QUINTAL",
        "source": "AGMARKNET",
        "state": (row.get("State") or row.get("state") or "").strip(),
        "district": (row.get("District") or row.get("district") or "").strip(),
        "mandi_name": (row.get("Market") or row.get("market") or "").strip(),
        "exchange_rate": None,
        "raw_file_hash": None,
    }


def _map_commodity(name: str) -> str | None:
    name_lower = name.lower()
    for keyword, code in COMMODITY_MAP.items():
        if keyword in name_lower:
            return code
    return None


def _parse_date(date_str: str) -> date | None:
    """Parses DD/MM/YYYY format returned by Agmarknet API."""
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        pass
    return None
