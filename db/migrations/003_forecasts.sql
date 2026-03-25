-- Migration 003: forecasts hypertable
-- Stores all model predictions with full provenance and accuracy tracking

CREATE TABLE IF NOT EXISTS forecasts (
    id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
    forecast_date           DATE        NOT NULL,   -- date this forecast was GENERATED
    target_date             DATE        NOT NULL,   -- date being FORECAST
    commodity               VARCHAR(20) NOT NULL,
    district                VARCHAR(100),           -- NULL = state-level

    -- Prediction outputs
    direction               VARCHAR(10) NOT NULL,   -- 'UP', 'DOWN', 'STABLE'
    predicted_price_inr     NUMERIC(10,2),
    confidence_score        NUMERIC(4,3) NOT NULL,  -- 0.000 to 1.000
    prediction_interval_low  NUMERIC(10,2),
    prediction_interval_high NUMERIC(10,2),

    -- Model provenance (required for reproducibility)
    model_name              VARCHAR(50) NOT NULL,   -- 'HEURISTIC_v1', 'PROPHET_v1', 'ENSEMBLE_v1'
    model_version           VARCHAR(20) NOT NULL,
    model_artifact_path     VARCHAR(500),
    features_snapshot       JSONB,                  -- feature values at prediction time

    -- Actuals (filled when target_date passes by analytics-service)
    actual_price_inr        NUMERIC(10,2),
    actual_direction        VARCHAR(10),
    accuracy_flag           BOOLEAN,                -- was direction correct?
    evaluated_at            TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, forecast_date)
);

SELECT create_hypertable('forecasts', 'forecast_date',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_forecasts_lookup
    ON forecasts (commodity, target_date, model_name);
CREATE INDEX IF NOT EXISTS idx_forecasts_latest
    ON forecasts (commodity, forecast_date DESC, target_date);
CREATE INDEX IF NOT EXISTS idx_forecasts_accuracy
    ON forecasts (commodity, evaluated_at)
    WHERE accuracy_flag IS NOT NULL;

COMMENT ON TABLE forecasts IS
    'All model predictions with confidence scores and accuracy tracking. model_version is mandatory for every row.';
COMMENT ON COLUMN forecasts.features_snapshot IS
    'JSONB snapshot of all feature values used for this prediction. Required for reproducibility.';
