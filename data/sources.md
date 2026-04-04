# KrishiNiti — Real Data Sources

> Maintained automatically by the `data-collector` agent.
> Every source used in this project is logged here.
> **Rule: No data enters the project without a source entry here.**

---

<!-- Sources will be appended below by the data-collector agent -->

## Fertilizer Prices — World Bank Commodity Price Data (Pink Sheet)
- **URL**: https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx
- **What it contains**: Monthly global prices for Urea, DAP, MOP in USD/MT since 1960
- **Format**: Excel (.xlsx)
- **Update frequency**: Monthly
- **Date first accessed**: 2026-03-26
- **Records**: 2298 rows, 1960-01-01 to 2026-02-01
- **SHA256**: 3e82489e51d91d74d797e7f1f9b39695...
- **How to refresh**: Run `python scripts/fetch_worldbank_pinksheet.py`
- **Notes**: Column names verified in 'Monthly Prices' sheet. Prices in USD/MT, convert to INR in seed_db.py using RBI exchange rate.

## Weather Data — NASA POWER API (All India, Historical Daily)
- **URL**: https://power.larc.nasa.gov/api/temporal/daily/point
- **What it contains**: Daily temperature, precipitation, humidity, wind for 50 Indian farming districts
- **Format**: JSON per district
- **States covered**: Andhra Pradesh, Assam, Bihar, Chhattisgarh, Gujarat, Haryana, Himachal Pradesh, Jharkhand, Karnataka, Kerala, Madhya Pradesh, Maharashtra, Odisha, Punjab, Rajasthan, Tamil Nadu, Telangana, Uttar Pradesh, Uttarakhand, West Bengal
- **Districts**: 50 total
- **Parameters**: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS10M
- **Date range**: 20140101 to 20260326
- **Total records**: ~223,391
- **Date first accessed**: 2026-03-26
- **How to refresh**: Run `python scripts/fetch_nasa_power.py`
- **Notes**: Free, no API key. Missing data = -999 (filter before use). Community=AG.

## Fertilizer Prices — World Bank Commodity Price Data (Pink Sheet)
- **URL**: https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx
- **What it contains**: Monthly global prices for Urea, DAP, MOP in USD/MT since 1960
- **Format**: Excel (.xlsx)
- **Update frequency**: Monthly
- **Date first accessed**: 2026-03-28
- **Records**: 2298 rows, 1960-01-01 to 2026-02-01
- **SHA256**: 3e82489e51d91d74d797e7f1f9b39695...
- **How to refresh**: Run `python scripts/fetch_worldbank_pinksheet.py`
- **Notes**: Column names verified in 'Monthly Prices' sheet. Prices in USD/MT, convert to INR in seed_db.py using RBI exchange rate.

## Weather Data — NASA POWER API (All India, Historical Daily)
- **URL**: https://power.larc.nasa.gov/api/temporal/daily/point
- **What it contains**: Daily temperature, precipitation, humidity, wind for 50 Indian farming districts
- **Format**: JSON per district
- **States covered**: Andhra Pradesh, Assam, Bihar, Chhattisgarh, Gujarat, Haryana, Himachal Pradesh, Jharkhand, Karnataka, Kerala, Madhya Pradesh, Maharashtra, Odisha, Punjab, Rajasthan, Tamil Nadu, Telangana, Uttar Pradesh, Uttarakhand, West Bengal
- **Districts**: 50 total
- **Parameters**: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS10M
- **Date range**: 20140101 to 20260328
- **Total records**: ~223,500
- **Date first accessed**: 2026-03-28
- **How to refresh**: Run `python scripts/fetch_nasa_power.py`
- **Notes**: Free, no API key. Missing data = -999 (filter before use). Community=AG.
