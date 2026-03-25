-- Migration 002: weather_data hypertable
-- Stores historical and forecast weather for Gujarat farming districts

CREATE TABLE IF NOT EXISTS weather_data (
    id                  BIGSERIAL,
    observation_date    DATE            NOT NULL,
    district            VARCHAR(100)    NOT NULL,
    state               VARCHAR(100)    NOT NULL,
    latitude            NUMERIC(8,5)    NOT NULL,
    longitude           NUMERIC(8,5)    NOT NULL,
    temp_max_c          NUMERIC(5,2),
    temp_min_c          NUMERIC(5,2),
    temp_avg_c          NUMERIC(5,2),
    precipitation_mm    NUMERIC(7,2),
    humidity_pct        NUMERIC(5,2),
    wind_speed_ms       NUMERIC(6,2),
    source              VARCHAR(30)     NOT NULL,   -- 'NASA_POWER', 'OPEN_METEO', 'IMD'
    is_forecast         BOOLEAN         NOT NULL DEFAULT FALSE,
    forecast_made_at    TIMESTAMPTZ,               -- NULL for historical observations
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, observation_date)
);

SELECT create_hypertable('weather_data', 'observation_date',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_weather_unique
    ON weather_data (observation_date, district, source, is_forecast);

CREATE INDEX IF NOT EXISTS idx_weather_district_date
    ON weather_data (district, observation_date DESC);

COMMENT ON TABLE weather_data IS
    'Daily weather observations and forecasts per Gujarat district. is_forecast=TRUE for future predictions.';
