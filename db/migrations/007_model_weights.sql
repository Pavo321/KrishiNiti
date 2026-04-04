-- Model weights table: stores adaptive ensemble weights per commodity per model.
-- Updated nightly by analytics-service POST /api/v1/accuracy/compute-weights.
-- Read at runtime by ensemble.py to pick the best-performing model mix.

CREATE TABLE IF NOT EXISTS model_weights (
    id            BIGSERIAL PRIMARY KEY,
    commodity     VARCHAR(20)   NOT NULL,
    model_name    VARCHAR(50)   NOT NULL,
    weight        NUMERIC(5,3)  NOT NULL CHECK (weight >= 0.10 AND weight <= 1.0),
    sample_size   INTEGER       NOT NULL DEFAULT 0,
    computed_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS model_weights_commodity_model_uidx
    ON model_weights (commodity, model_name);

CREATE INDEX IF NOT EXISTS model_weights_computed_at_idx
    ON model_weights (computed_at DESC);

COMMENT ON TABLE model_weights IS
    'Adaptive ensemble weights computed from last-60-day directional accuracy per model. '
    'Floor 0.10 ensures no model is fully ignored. Updated nightly.';
