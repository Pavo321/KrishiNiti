-- Migration 005: alert_log hypertable
-- Every WhatsApp message sent, delivery status, farmer response, and outcome

CREATE TABLE IF NOT EXISTS alert_log (
    id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    farmer_id           UUID        NOT NULL REFERENCES farmers(id),
    forecast_id         UUID        NOT NULL,

    -- Message
    message_template    VARCHAR(100) NOT NULL,  -- 'PRICE_BUY_WINDOW', 'PRICE_WAIT', 'WEEKLY_SUMMARY'
    message_language    VARCHAR(10)  NOT NULL DEFAULT 'gu',
    message_text_hash   VARCHAR(64),            -- SHA256 of rendered message (no PII in logs)

    -- WhatsApp delivery tracking
    whatsapp_message_id VARCHAR(200),
    delivery_status     VARCHAR(20)  NOT NULL DEFAULT 'SENT',
    -- Values: 'SENT', 'DELIVERED', 'READ', 'FAILED', 'BOUNCED'
    delivered_at        TIMESTAMPTZ,
    read_at             TIMESTAMPTZ,

    -- Farmer response
    farmer_reply        VARCHAR(500),
    reply_received_at   TIMESTAMPTZ,

    -- Outcome
    farmer_acted        BOOLEAN,   -- did farmer confirm purchase?
    acted_at            TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, sent_at)
);

SELECT create_hypertable('alert_log', 'sent_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_alert_log_farmer
    ON alert_log (farmer_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_forecast
    ON alert_log (forecast_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_delivery
    ON alert_log (delivery_status, sent_at DESC);

COMMENT ON TABLE alert_log IS
    'Immutable log of every alert sent. message_text_hash stored instead of message text to avoid PII in logs.';
