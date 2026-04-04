"""
Open-Meteo weather fetcher — replaces NASA POWER.
Free, no API key. ERA5 reanalysis gives 40yr historical + 15-day forecast.
"""

import logging
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

# 50 major Indian agricultural districts with lat/long
DISTRICTS = [
    ("Punjab",          "Ludhiana",       30.9010, 75.8573),
    ("Punjab",          "Amritsar",       31.6340, 74.8723),
    ("Haryana",         "Karnal",         29.6857, 76.9905),
    ("Haryana",         "Hisar",          29.1542, 75.7217),
    ("Uttar Pradesh",   "Lucknow",        26.8467, 80.9462),
    ("Uttar Pradesh",   "Agra",           27.1767, 78.0081),
    ("Uttar Pradesh",   "Varanasi",       25.3176, 82.9739),
    ("Uttar Pradesh",   "Meerut",         28.9845, 77.7064),
    ("Rajasthan",       "Jaipur",         26.9124, 75.7873),
    ("Rajasthan",       "Jodhpur",        26.2389, 73.0243),
    ("Madhya Pradesh",  "Bhopal",         23.2599, 77.4126),
    ("Madhya Pradesh",  "Indore",         22.7196, 75.8577),
    ("Madhya Pradesh",  "Jabalpur",       23.1815, 79.9864),
    ("Gujarat",         "Ahmedabad",      23.0225, 72.5714),
    ("Gujarat",         "Rajkot",         22.3039, 70.8022),
    ("Gujarat",         "Surat",          21.1702, 72.8311),
    ("Gujarat",         "Anand",          22.5645, 72.9289),
    ("Maharashtra",     "Nagpur",         21.1458, 79.0882),
    ("Maharashtra",     "Pune",           18.5204, 73.8567),
    ("Maharashtra",     "Aurangabad",     19.8762, 75.3433),
    ("Maharashtra",     "Nashik",         19.9975, 73.7898),
    ("Bihar",           "Patna",          25.5941, 85.1376),
    ("Bihar",           "Muzaffarpur",    26.1197, 85.3910),
    ("West Bengal",     "Kolkata",        22.5726, 88.3639),
    ("West Bengal",     "Bardhaman",      23.2324, 87.8615),
    ("Andhra Pradesh",  "Vijayawada",     16.5062, 80.6480),
    ("Andhra Pradesh",  "Guntur",         16.3067, 80.4365),
    ("Telangana",       "Hyderabad",      17.3850, 78.4867),
    ("Telangana",       "Warangal",       17.9784, 79.5941),
    ("Karnataka",       "Bangalore",      12.9716, 77.5946),
    ("Karnataka",       "Hubli",          15.3647, 75.1240),
    ("Karnataka",       "Davangere",      14.4644, 75.9218),
    ("Tamil Nadu",      "Chennai",        13.0827, 80.2707),
    ("Tamil Nadu",      "Coimbatore",     11.0168, 76.9558),
    ("Tamil Nadu",      "Madurai",         9.9252, 78.1198),
    ("Kerala",          "Thiruvananthapuram", 8.5241, 76.9366),
    ("Odisha",          "Bhubaneswar",    20.2961, 85.8245),
    ("Odisha",          "Cuttack",        20.4625, 85.8828),
    ("Chhattisgarh",    "Raipur",         21.2514, 81.6296),
    ("Jharkhand",       "Ranchi",         23.3441, 85.3096),
    ("Assam",           "Guwahati",       26.1445, 91.7362),
    ("Himachal Pradesh","Shimla",         31.1048, 77.1734),
    ("Uttarakhand",     "Dehradun",       30.3165, 78.0322),
    ("Punjab",          "Patiala",        30.3398, 76.3869),
    ("Rajasthan",       "Kota",           25.2138, 75.8648),
    ("Uttar Pradesh",   "Kanpur",         26.4499, 80.3319),
    ("Maharashtra",     "Kolhapur",       16.7050, 74.2433),
    ("Gujarat",         "Vadodara",       22.3072, 73.1812),
    ("Madhya Pradesh",  "Gwalior",        26.2183, 78.1828),
    ("Bihar",           "Gaya",           24.7955, 85.0002),
]

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

VARIABLES = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,relative_humidity_2m_mean,wind_speed_10m_mean"


def fetch_historical_weather(start_date: date, end_date: date) -> list[dict]:
    """
    Fetches daily historical weather for all districts between start_date and end_date.
    Uses ERA5 reanalysis — 40yr history available.
    """
    all_records = []

    for state, district, lat, lon in DISTRICTS:
        try:
            records = _fetch_district(
                state, district, lat, lon,
                start_date.isoformat(), end_date.isoformat(),
                is_forecast=False
            )
            all_records.extend(records)
        except Exception as e:
            logger.warning(f"Open-Meteo failed for {district}, {state}: {e}")
            continue

    logger.info(f"Open-Meteo: fetched {len(all_records)} weather records for {len(DISTRICTS)} districts")
    return all_records


def fetch_forecast_weather() -> list[dict]:
    """Fetches 15-day forecast for all districts."""
    all_records = []
    today = date.today()
    end = today + timedelta(days=15)

    for state, district, lat, lon in DISTRICTS:
        try:
            url = FORECAST_URL
            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": VARIABLES,
                "start_date": today.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "Asia/Kolkata",
            }
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
            data = resp.json()
            records = _parse_response(data, state, district, is_forecast=True)
            all_records.extend(records)
        except Exception as e:
            logger.warning(f"Open-Meteo forecast failed for {district}: {e}")
            continue

    return all_records


def _fetch_district(state, district, lat, lon, start, end, is_forecast) -> list[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": VARIABLES,
        "start_date": start,
        "end_date": end,
        "timezone": "Asia/Kolkata",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.get(BASE_URL, params=params)
        resp.raise_for_status()
    return _parse_response(resp.json(), state, district, is_forecast)


def _parse_response(data: dict, state: str, district: str, is_forecast: bool) -> list[dict]:
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    records = []

    for i, d in enumerate(dates):
        def val(key):
            arr = daily.get(key, [])
            return float(arr[i]) if i < len(arr) and arr[i] is not None else None

        records.append({
            "observation_date": d,
            "district": district,
            "state": state,
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "temp_max_c": val("temperature_2m_max"),
            "temp_min_c": val("temperature_2m_min"),
            "temp_avg_c": val("temperature_2m_mean"),
            "precipitation_mm": val("precipitation_sum"),
            "humidity_pct": val("relative_humidity_2m_mean"),
            "wind_speed_ms": val("wind_speed_10m_mean"),
            "source": "OPEN_METEO",
            "is_forecast": is_forecast,
        })

    return records
