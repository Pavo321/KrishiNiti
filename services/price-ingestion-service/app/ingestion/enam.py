"""
eNAM (National Agriculture Market) transaction price fetcher.
Fetches real cleared transaction prices from data.gov.in eNAM dataset.
Unlike Agmarknet (arrivals), eNAM gives actual cleared prices — closer to
what farmers and traders paid.
Uses existing data.gov.in API key.
"""

import logging
import os
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

# eNAM dataset on data.gov.in
ENAM_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"  # verified commodity prices
ENAM_API_URL = f"https://api.data.gov.in/resource/{ENAM_RESOURCE_ID}"

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
    "10:26:26": "NPK_102626",
    "npk 12:32:16": "NPK_123216",
    "12:32:16": "NPK_123216",
}


def fetch_enam_prices(days_back: int = 1) -> list[dict]:
    """
    Fetches eNAM transaction prices from data.gov.in.
    days_back=1 for daily run (yesterday), larger for backfill.
    """
    api_key = os.environ.get("DATA_GOV_API_KEY", os.environ.get("DATA_GOV_IN_API_KEY", ""))
    if not api_key:
        logger.warning("eNAM: DATA_GOV_API_KEY not set, skipping")
        return []

    today = date.today()
    from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    all_records = []

    for commodity_query, commodity_code in [
        ("Urea", "UREA"), ("DAP", "DAP"), ("MOP", "MOP"),
        ("SSP", "SSP"), ("Single Super Phosphate", "SSP"),
        ("NPK", "NPK_102626"),
    ]:
        try:
            records = _fetch_commodity(api_key, commodity_query, commodity_code, from_date, to_date)
            all_records.extend(records)
        except Exception as e:
            logger.warning(f"eNAM fetch failed for {commodity_query}: {e}")

    logger.info(f"eNAM: fetched {len(all_records)} transaction price records")
    return all_records


def _fetch_commodity(api_key: str, query: str, code: str, from_date: str, to_date: str) -> list[dict]:
    records = []
    offset = 0
    limit = 500

    while True:
        params = {
            "api-key": api_key,
            "format": "json",
            "filters[commodity]": query,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
            "offset": offset,
        }

        with httpx.Client(timeout=30) as client:
            resp = client.get(ENAM_API_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        rows = data.get("records", [])
        if not rows:
            break

        for row in rows:
            price = _safe_float(row.get("modal_price", row.get("price")))
            if not price or price <= 0:
                continue

            arrival_date = row.get("arrival_date", row.get("date", ""))
            parsed_date = _parse_date(arrival_date)
            if not parsed_date:
                continue

            # eNAM prices are per quintal (100kg) → convert to per 50kg bag
            price_per_bag = price * 0.5

            records.append({
                "price_date": parsed_date,
                "commodity": code,
                "price_inr": round(price_per_bag, 2),
                "price_usd": None,
                "unit": "INR_PER_BAG",
                "source": "ENAM",
                "state": row.get("state", ""),
                "district": row.get("district", ""),
                "mandi_name": row.get("market", row.get("mandi", "")),
                "exchange_rate": None,
                "raw_file_hash": None,
            })

        if len(rows) < limit:
            break
        offset += limit

    return records


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_date(date_str: str) -> date | None:
    if not date_str:
        return None
    from datetime import datetime
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            continue
    return None
