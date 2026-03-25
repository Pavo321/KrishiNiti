-- Migration 001: commodity_prices hypertable
-- Stores Urea, DAP, MOP prices from World Bank, Agmarknet, fert.nic.in

CREATE TABLE IF NOT EXISTS commodity_prices (
    id              BIGSERIAL,
    price_date      DATE            NOT NULL,
    commodity       VARCHAR(20)     NOT NULL,   -- 'UREA', 'DAP', 'MOP'
    price_inr       NUMERIC(10,2),              -- INR per 50kg bag or per MT
    price_usd       NUMERIC(10,2),              -- USD per MT (World Bank data)
    unit            VARCHAR(20)     NOT NULL,   -- 'INR_PER_BAG', 'USD_PER_MT', 'INR_PER_MT'
    source          VARCHAR(50)     NOT NULL,   -- 'WORLDBANK', 'AGMARKNET', 'FERT_NIC', 'ENAM'
    state           VARCHAR(50),
    district        VARCHAR(100),
    mandi_name      VARCHAR(200),
    exchange_rate   NUMERIC(8,4),               -- INR/USD rate used for conversion
    raw_file_hash   VARCHAR(64),                -- SHA256 of source file
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, price_date)
);

SELECT create_hypertable('commodity_prices', 'price_date',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_commodity_prices_unique
    ON commodity_prices (
        price_date,
        commodity,
        source,
        COALESCE(district, ''),
        COALESCE(mandi_name, '')
    );

CREATE INDEX IF NOT EXISTS idx_commodity_prices_lookup
    ON commodity_prices (commodity, source, price_date DESC);

CREATE INDEX IF NOT EXISTS idx_commodity_prices_district
    ON commodity_prices (district, commodity, price_date DESC)
    WHERE district IS NOT NULL;

COMMENT ON TABLE commodity_prices IS
    'Daily/monthly fertilizer and commodity prices from multiple sources. TimescaleDB hypertable.';
COMMENT ON COLUMN commodity_prices.raw_file_hash IS
    'SHA256 of source file for data provenance. Links to data/sources.md entry.';
