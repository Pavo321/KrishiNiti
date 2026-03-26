"""
Fetches real historical weather data from NASA POWER API for major Indian farming districts.
Source: https://power.larc.nasa.gov/
No API key required. Free for research and agricultural use.
Covers all major agricultural zones across India.
"""

import json
import time
from datetime import date
from pathlib import Path

import httpx

OUTPUT_DIR = Path("data/raw/weather")
SOURCES_FILE = Path("data/sources.md")

NASA_POWER_API = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Major farming districts across all Indian states
# Covers all major crop zones: wheat belt, rice bowl, cotton, sugarcane, pulses, oilseeds
INDIA_DISTRICTS = [
    # Gujarat
    {"name": "Ahmedabad",   "state": "Gujarat",         "lat": 23.03, "lon": 72.58},
    {"name": "Anand",       "state": "Gujarat",         "lat": 22.56, "lon": 72.95},
    {"name": "Rajkot",      "state": "Gujarat",         "lat": 22.30, "lon": 70.80},
    {"name": "Junagadh",    "state": "Gujarat",         "lat": 21.52, "lon": 70.46},
    # Punjab (wheat belt)
    {"name": "Ludhiana",    "state": "Punjab",          "lat": 30.90, "lon": 75.85},
    {"name": "Amritsar",    "state": "Punjab",          "lat": 31.63, "lon": 74.87},
    {"name": "Patiala",     "state": "Punjab",          "lat": 30.34, "lon": 76.38},
    # Haryana
    {"name": "Karnal",      "state": "Haryana",         "lat": 29.69, "lon": 76.99},
    {"name": "Hisar",       "state": "Haryana",         "lat": 29.15, "lon": 75.72},
    # Uttar Pradesh (largest agri state)
    {"name": "Lucknow",     "state": "Uttar Pradesh",   "lat": 26.85, "lon": 80.95},
    {"name": "Agra",        "state": "Uttar Pradesh",   "lat": 27.18, "lon": 78.01},
    {"name": "Varanasi",    "state": "Uttar Pradesh",   "lat": 25.32, "lon": 83.00},
    {"name": "Kanpur",      "state": "Uttar Pradesh",   "lat": 26.45, "lon": 80.33},
    # Madhya Pradesh
    {"name": "Indore",      "state": "Madhya Pradesh",  "lat": 22.72, "lon": 75.86},
    {"name": "Bhopal",      "state": "Madhya Pradesh",  "lat": 23.26, "lon": 77.40},
    {"name": "Jabalpur",    "state": "Madhya Pradesh",  "lat": 23.16, "lon": 79.95},
    # Maharashtra
    {"name": "Pune",        "state": "Maharashtra",     "lat": 18.52, "lon": 73.86},
    {"name": "Nashik",      "state": "Maharashtra",     "lat": 20.00, "lon": 73.79},
    {"name": "Aurangabad",  "state": "Maharashtra",     "lat": 19.88, "lon": 75.34},
    {"name": "Nagpur",      "state": "Maharashtra",     "lat": 21.15, "lon": 79.09},
    # Rajasthan
    {"name": "Jaipur",      "state": "Rajasthan",       "lat": 26.91, "lon": 75.79},
    {"name": "Kota",        "state": "Rajasthan",       "lat": 25.18, "lon": 75.84},
    {"name": "Bikaner",     "state": "Rajasthan",       "lat": 28.02, "lon": 73.31},
    # Bihar (rice + wheat)
    {"name": "Patna",       "state": "Bihar",           "lat": 25.59, "lon": 85.14},
    {"name": "Muzaffarpur", "state": "Bihar",           "lat": 26.12, "lon": 85.39},
    {"name": "Gaya",        "state": "Bihar",           "lat": 24.80, "lon": 85.00},
    # West Bengal (rice bowl)
    {"name": "Kolkata",     "state": "West Bengal",     "lat": 22.57, "lon": 88.36},
    {"name": "Bardhaman",   "state": "West Bengal",     "lat": 23.25, "lon": 87.86},
    {"name": "Murshidabad", "state": "West Bengal",     "lat": 24.18, "lon": 88.27},
    # Andhra Pradesh
    {"name": "Vijayawada",  "state": "Andhra Pradesh",  "lat": 16.51, "lon": 80.63},
    {"name": "Guntur",      "state": "Andhra Pradesh",  "lat": 16.31, "lon": 80.44},
    {"name": "Kurnool",     "state": "Andhra Pradesh",  "lat": 15.83, "lon": 78.05},
    # Telangana
    {"name": "Hyderabad",   "state": "Telangana",       "lat": 17.38, "lon": 78.49},
    {"name": "Warangal",    "state": "Telangana",       "lat": 18.00, "lon": 79.58},
    # Karnataka
    {"name": "Bangalore",   "state": "Karnataka",       "lat": 12.97, "lon": 77.59},
    {"name": "Dharwad",     "state": "Karnataka",       "lat": 15.45, "lon": 75.01},
    {"name": "Mysore",      "state": "Karnataka",       "lat": 12.30, "lon": 76.65},
    # Tamil Nadu
    {"name": "Chennai",     "state": "Tamil Nadu",      "lat": 13.08, "lon": 80.27},
    {"name": "Coimbatore",  "state": "Tamil Nadu",      "lat": 11.00, "lon": 76.96},
    {"name": "Madurai",     "state": "Tamil Nadu",      "lat": 9.93,  "lon": 78.12},
    # Odisha
    {"name": "Bhubaneswar", "state": "Odisha",          "lat": 20.30, "lon": 85.82},
    {"name": "Cuttack",     "state": "Odisha",          "lat": 20.46, "lon": 85.88},
    # Chhattisgarh
    {"name": "Raipur",      "state": "Chhattisgarh",    "lat": 21.25, "lon": 81.63},
    # Jharkhand
    {"name": "Ranchi",      "state": "Jharkhand",       "lat": 23.34, "lon": 85.31},
    # Assam
    {"name": "Guwahati",    "state": "Assam",           "lat": 26.14, "lon": 91.74},
    {"name": "Jorhat",      "state": "Assam",           "lat": 26.75, "lon": 94.22},
    # Kerala
    {"name": "Thrissur",    "state": "Kerala",          "lat": 10.52, "lon": 76.21},
    {"name": "Palakkad",    "state": "Kerala",          "lat": 10.78, "lon": 76.65},
    # Himachal Pradesh
    {"name": "Shimla",      "state": "Himachal Pradesh","lat": 31.10, "lon": 77.17},
    # Uttarakhand
    {"name": "Dehradun",    "state": "Uttarakhand",     "lat": 30.32, "lon": 78.03},
]

PARAMETERS = "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS10M"
START_DATE = "20140101"
END_DATE = date.today().strftime("%Y%m%d")


def fetch_district_weather(district: dict) -> dict:
    params = {
        "parameters": PARAMETERS,
        "community": "AG",
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
            "(Agricultural weather research for Indian farmers - all India; "
            "github.com/Pavo321/KrishiNiti)"
        )
    }

    print(f"  Fetching {district['name']}, {district['state']}...")

    with httpx.Client(headers=headers, timeout=180) as client:
        response = client.get(NASA_POWER_API, params=params)
        response.raise_for_status()

    data = response.json()
    params_data = data.get("properties", {}).get("parameter", {})

    if not params_data:
        raise ValueError(f"No data returned for {district['name']}, {district['state']}")

    record_count = len(params_data.get("T2M", {}))
    print(f"    {record_count} daily records")

    return {
        "district": district["name"],
        "state": district["state"],
        "latitude": district["lat"],
        "longitude": district["lon"],
        "start": START_DATE,
        "end": END_DATE,
        "source": "NASA_POWER",
        "parameters": PARAMETERS,
        "record_count": record_count,
        "data": params_data,
    }


def save_district_data(data: dict) -> Path:
    safe_name = data["district"].replace(" ", "_")
    safe_state = data["state"].replace(" ", "_")
    out_path = OUTPUT_DIR / f"{safe_state}_{safe_name}_nasa_power_{START_DATE}_{END_DATE}.json"
    with open(out_path, "w") as f:
        json.dump(data, f)
    return out_path


def update_sources_md(fetched: list[dict], total_records: int) -> None:
    states = sorted({d["state"] for d in fetched})
    entry = f"""
## Weather Data — NASA POWER API (All India, Historical Daily)
- **URL**: {NASA_POWER_API}
- **What it contains**: Daily temperature, precipitation, humidity, wind for {len(fetched)} Indian farming districts
- **Format**: JSON per district
- **States covered**: {', '.join(states)}
- **Districts**: {len(fetched)} total
- **Parameters**: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS10M
- **Date range**: {START_DATE} to {END_DATE}
- **Total records**: ~{total_records:,}
- **Date first accessed**: {date.today().isoformat()}
- **How to refresh**: Run `python scripts/fetch_nasa_power.py`
- **Notes**: Free, no API key. Missing data = -999 (filter before use). Community=AG.
"""
    with open(SOURCES_FILE, "a") as f:
        f.write(entry)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching weather for {len(INDIA_DISTRICTS)} districts across India...")
    fetched = []
    total_records = 0
    failed = []

    # Group by state for readable output
    current_state = None
    for i, district in enumerate(INDIA_DISTRICTS):
        if district["state"] != current_state:
            current_state = district["state"]
            print(f"\n[{current_state}]")

        try:
            data = fetch_district_weather(district)
            save_district_data(data)
            fetched.append(district)
            total_records += data["record_count"]

            if i < len(INDIA_DISTRICTS) - 1:
                time.sleep(2)   # respectful rate limiting

        except Exception as e:
            print(f"    FAILED: {e}")
            failed.append(f"{district['name']}, {district['state']}")

    print(f"\n{'='*50}")
    print(f"Done: {len(fetched)}/{len(INDIA_DISTRICTS)} districts fetched")
    print(f"Total records: ~{total_records:,}")

    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed)}")

    if fetched:
        update_sources_md(fetched, total_records)


if __name__ == "__main__":
    main()
