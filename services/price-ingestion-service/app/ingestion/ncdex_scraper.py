"""
NCDEX/MCX daily settlement price scraper.
Fetches Urea, DAP, MOP futures settlement prices.
No API key required — publicly available CSVs/HTML.
"""

import logging
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# NCDEX publishes daily settlement price reports
NCDEX_SETTLEMENT_URL = "https://www.ncdex.com/market-data/daily-settlement-price"

COMMODITY_MAP = {
    "UREA": ["UREA", "UREAMOP"],
    "DAP": ["DAP"],
    "MOP": ["MOP", "POTASH"],
    "SSP": ["SSP", "SUPERPHOSPHATE"],
    "NPK_102626": ["NPK", "COMPLEX"],
}


def fetch_settlement_prices(target_date: date | None = None) -> list[dict]:
    """
    Scrapes NCDEX daily settlement prices.
    Falls back to yesterday if today's data not yet published.
    Returns price records suitable for market_events table.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    records = []

    try:
        records.extend(_fetch_ncdex(target_date))
    except Exception as e:
        logger.warning(f"NCDEX scrape failed for {target_date}: {e}")

    logger.info(f"NCDEX/MCX: fetched {len(records)} settlement price records")
    return records


def _fetch_ncdex(target_date: date) -> list[dict]:
    """
    Fetches NCDEX settlement prices via their public data page.
    NCDEX publishes JSON via their API endpoint used by the website.
    """
    # NCDEX uses a date-parameterized endpoint
    date_str = target_date.strftime("%d-%m-%Y")
    api_url = f"https://www.ncdex.com/Memberzone/DailySettlementPrice?date={date_str}"

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; KrishiNiti-Research/1.0)",
        "Accept": "application/json, text/html",
        "Referer": "https://www.ncdex.com/market-data/daily-settlement-price",
    }

    records = []
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        resp = client.get(api_url)
        if resp.status_code != 200:
            logger.warning(f"NCDEX returned {resp.status_code} for {date_str}")
            return records

        # Try JSON first
        try:
            data = resp.json()
            records = _parse_ncdex_json(data, target_date)
        except Exception:
            # Fall back to HTML parsing
            records = _parse_ncdex_html(resp.text, target_date)

    return records


def _parse_ncdex_json(data, target_date: date) -> list[dict]:
    records = []
    items = data if isinstance(data, list) else data.get("data", data.get("rows", []))

    for item in items:
        symbol = str(item.get("symbol", item.get("Symbol", ""))).upper()
        commodity = _map_commodity(symbol)
        if not commodity:
            continue

        settlement_price = _safe_float(item.get("settlementPrice", item.get("SettlementPrice", item.get("settlement_price"))))
        if settlement_price is None or settlement_price <= 0:
            continue

        expiry = item.get("expiryDate", item.get("ExpiryDate", ""))
        contract = item.get("contractName", item.get("contract", symbol))

        records.append({
            "event_date": target_date.isoformat(),
            "event_type": "NCDEX_SETTLEMENT",
            "commodity": commodity,
            "description": f"NCDEX settlement price for {contract}: ₹{settlement_price}/MT",
            "source": "NCDEX",
            "price_inr": settlement_price,
            "contract": str(contract),
            "expiry_date": str(expiry),
        })

    return records


def _parse_ncdex_html(html: str, target_date: date) -> list[dict]:
    records = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return records

        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue

            row_dict = dict(zip(headers, cells))
            symbol = row_dict.get("symbol", row_dict.get("contract", "")).upper()
            commodity = _map_commodity(symbol)
            if not commodity:
                continue

            price_str = row_dict.get("settlement price", row_dict.get("price", ""))
            price = _safe_float(price_str)
            if price and price > 0:
                records.append({
                    "event_date": target_date.isoformat(),
                    "event_type": "NCDEX_SETTLEMENT",
                    "commodity": commodity,
                    "description": f"NCDEX {symbol}: ₹{price}/MT",
                    "source": "NCDEX",
                    "price_inr": price,
                    "contract": symbol,
                    "expiry_date": "",
                })
    except Exception as e:
        logger.warning(f"HTML parse failed: {e}")

    return records


def _map_commodity(symbol: str) -> str | None:
    for commodity, keywords in COMMODITY_MAP.items():
        for kw in keywords:
            if kw in symbol:
                return commodity
    return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
