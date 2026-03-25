-- KrishiNiti PostgreSQL + TimescaleDB initialization
-- Runs automatically on first container start

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Run all migrations in order
\i /docker-entrypoint-initdb.d/migrations/001_commodity_prices.sql
\i /docker-entrypoint-initdb.d/migrations/002_weather_data.sql
\i /docker-entrypoint-initdb.d/migrations/003_forecasts.sql
\i /docker-entrypoint-initdb.d/migrations/004_farmers.sql
\i /docker-entrypoint-initdb.d/migrations/005_alert_log.sql
