-- Migration 006: market_events table
-- Stores discrete events that affect fertilizer demand/price:
--   - PM-KISAN tranche releases (demand surge signal)
--   - NCDEX futures settlement prices
--   - Kharif/Rabi season start dates
--   - Government subsidy announcements
--   - RBI agri credit seasonal signals

CREATE TABLE IF NOT EXISTS market_events (
    id              BIGSERIAL       PRIMARY KEY,
    event_date      DATE            NOT NULL,
    event_type      VARCHAR(50)     NOT NULL,   -- 'PMKISAN_TRANCHE', 'NCDEX_SETTLEMENT', 'KHARIF_SEASON_START', etc.
    commodity       VARCHAR(20),                -- NULL if economy-wide event
    description     TEXT,
    source          VARCHAR(50)     NOT NULL,
    price_inr       NUMERIC(10,2),              -- for NCDEX settlement prices
    contract        VARCHAR(50),                -- for futures contracts
    expiry_date     VARCHAR(20),                -- futures expiry
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_events_unique
    ON market_events (event_date, event_type, COALESCE(commodity, ''), COALESCE(contract, ''));

CREATE INDEX IF NOT EXISTS idx_market_events_date
    ON market_events (event_date DESC);

CREATE INDEX IF NOT EXISTS idx_market_events_type
    ON market_events (event_type, event_date DESC);

COMMENT ON TABLE market_events IS
    'Discrete market events used as features for XGBoost and TFT models. PM-KISAN tranches, futures prices, seasonal signals.';
