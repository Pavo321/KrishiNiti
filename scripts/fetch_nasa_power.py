"""
Fetches real historical weather data from NASA POWER API for Gujarat farming districts.
Source: https://power.larc.nasa.gov/
No API key required. Free for research and agricultural use.
"""

import json
import time
from datetime import date
from pathlib import Path

import httpx

OUTPUT_DIR = Path("data/raw/weather")
SOURCES_FILE = Path("data/sources.md")

NASA_POWER_API = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Gujarat farming districts with coordinates
GUJARAT_DISTRICTS = [
    {"name": "Ahmedabad", "lat": 23.03, "lon": 72.58},
    {"name": "Anand",     "lat": 22.56, "lon": 72.95},
    {"name": "Kheda",     "lat": 22.75, "lon": 72.68},
    {"name": "Mehsana",   "lat": 23.59, "lon": 72.38},
    {"name": "Rajkot",    "lat": 22.30, "lon": 70.80},
    {"name": "Surat",     "lat": 21.17, "lon": 72.83},
]

# Parameters: Temperature (max/min/avg), Precipitation, Humidity, Wind
PARAMETERS = "T2M,T2MDEW,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS10M"

# Fetch 10 years of historical data
START_DATE = "20140101"
END_DATE = date.today().strftime("%Y%m%d")


def fetch_district_weather(district: dict) -> dict:
    params = {
        "parameters": PARAMETERS,
        "community": "AG",  # Agriculture community dataset
        "longitude": district["lon"],
        "latitude": district["lat"],
        "start": START_DATE,
        "end": END_DATE,
        "format": "JSON",
        "header": "true",
        "time-standard": "LST",
    }

    headers = {
        "User-Agent": (
            "KrishiNiti-DataPipeline/1.0 "
            "(Agricultural weather research for Indian farmers; "
            "github.com/Pavo321/KrishiNiti)"
        )
    }

    print(f"Fetching {district['name']} ({district['lat']}, {district['lon']})...")

    with httpx.Client(headers=headers, timeout=180) as client:
        response = client.get(NASA_POWER_API, params=params)
        response.raise_for_status()

    data = response.json()

    # Verify we got real data
    params_data = data.get("properties", {}).get("parameter", {})
    if not params_data:
        raise ValueError(
            f"No parameter data returned for {district['name']}. "
            f"Response: {json.dumps(data)[:500]}"
        )

    t2m = params_data.get("T2M", {})
    record_count = len(t2m)
    print(f"  Got {record_count} daily records for {district['name']}")

    # Spot check: temperature should be between 5°C and 50°C for Gujarat
    sample_values = list(t2m.values())[:10]
    for v in sample_values:
        if v != -999 and not (5 < v < 50):  # -999 is NASA POWER missing data flag
            print(
                f"  WARNING: Temperature {v}°C outside expected Gujarat range. "
                "Check data manually."
            )
            break

    return {
        "district": district["name"],
        "latitude": district["lat"],
        "longitude": district["lon"],
        "start": START_DATE,
        "end": END_DATE,
        "source": "NASA_POWER",
        "parameters": PARAMETERS,
        "record_count": record_count,
        "data": params_data,
    }


def save_district_data(district_name: str, data: dict) -> Path:
    out_path = OUTPUT_DIR / f"{district_name}_nasa_power_{START_DATE}_{END_DATE}.json"
    with open(out_path, "w") as f:
        json.dump(data, f)
    print(f"  Saved to {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    return out_path


def update_sources_md(districts_fetched: list[str], record_count: int) -> None:
    entry = f"""
## Weather Data — NASA POWER API (Historical Daily)
- **URL**: {NASA_POWER_API}
- **What it contains**: Daily temperature (max/min/avg), precipitation, humidity, wind for Gujarat districts
- **Format**: JSON
- **Update frequency**: Daily (real-time lag ~3 days)
- **Date first accessed**: {date.today().isoformat()}
- **Districts**: {', '.join(districts_fetched)}
- **Parameters**: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS10M
- **Date range**: {START_DATE} to {END_DATE}
- **Records**: ~{record_count} daily observations per district
- **How to refresh**: Run `python scripts/fetch_nasa_power.py`
- **Notes**: Free, no API key. Missing data coded as -999 (filter before use). Community=AG for agriculture-specific parameters.
"""
    with open(SOURCES_FILE, "a") as f:
        f.write(entry)
    print(f"Updated {SOURCES_FILE}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fetched_districts = []
    total_records = 0

    for i, district in enumerate(GUJARAT_DISTRICTS):
        try:
            data = fetch_district_weather(district)
            save_district_data(district["name"], data)
            fetched_districts.append(district["name"])
            total_records += data["record_count"]

            # Respectful rate limiting — NASA POWER asks for reasonable usage
            if i < len(GUJARAT_DISTRICTS) - 1:
                print("  Waiting 3s before next request...")
                time.sleep(3)

        except httpx.HTTPStatusError as e:
            print(f"HTTP error for {district['name']}: {e.response.status_code}")
            print("Continuing with next district...")
        except Exception as e:
            print(f"Error fetching {district['name']}: {e}")
            print("Continuing with next district...")

    if fetched_districts:
        update_sources_md(fetched_districts, total_records // len(fetched_districts))
        print(
            f"\nDone. Fetched {len(fetched_districts)}/{len(GUJARAT_DISTRICTS)} districts, "
            f"~{total_records} total daily records."
        )
    else:
        print("ERROR: No districts fetched successfully.")


if __name__ == "__main__":
    main()
