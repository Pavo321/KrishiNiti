# KrishiNiti 🌾

**AI Farm Input Timing Optimizer** — predicts the best time for Indian farmers to buy fertilizers (Urea, DAP, MOP) and seeds, saving 25–40% on input costs. Alerts delivered via WhatsApp in Gujarati.

## Quick Start

```bash
# 1. Clone and setup
cp .env.example .env
# Fill in POSTGRES_PASSWORD and REDIS_PASSWORD at minimum

# 2. Start infrastructure
docker-compose up -d postgres redis

# 3. Fetch real data (no fake data — ever)
pip install httpx openpyxl
python scripts/fetch_worldbank_pinksheet.py
python scripts/fetch_nasa_power.py

# 4. Seed the database
pip install psycopg2-binary
python scripts/seed_db.py

# 5. Start all services
docker-compose up
```

Services run at:
- Price Ingestion: http://localhost:8001
- Weather: http://localhost:8002
- Forecast: http://localhost:8003
- Alerts: http://localhost:8004
- Farmers: http://localhost:8005
- Analytics: http://localhost:8006
- Frontend: http://localhost:3000

## Architecture

```
World Bank / Agmarknet / NASA POWER
        ↓
price-ingestion-service  weather-service
        ↓                      ↓
        └──── forecast-service ┘
                    ↓
             alert-service ──→ WhatsApp (Gujarati)
                    ↓
            analytics-service (accuracy tracking)
```

## Real Data Sources
All sources documented in [data/sources.md](data/sources.md). No synthetic data is used anywhere in this project.

## Services
| Service | Port | Responsibility |
|---------|------|---------------|
| price-ingestion | 8001 | Daily Urea/DAP/MOP price fetch from World Bank + Agmarknet |
| weather | 8002 | Daily weather from NASA POWER + Open-Meteo |
| forecast | 8003 | LSTM + Prophet ensemble, daily predictions |
| alert | 8004 | WhatsApp Business API, Gujarati messages |
| farmer | 8005 | Farmer profiles, PII encrypted, DPDP Act compliant |
| analytics | 8006 | Prediction accuracy tracking, delivery rates |

## Contributing
See [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) for PR checklist.
