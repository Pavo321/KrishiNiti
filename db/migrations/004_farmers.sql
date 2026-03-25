-- Migration 004: farmers table
-- PII stored encrypted. Consent tracked for DPDP Act 2023 compliance.

CREATE TABLE IF NOT EXISTS farmers (
    id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,

    -- PII — field-level encrypted at application layer (AES-256)
    phone_number_enc        BYTEA       NOT NULL,
    phone_hash              VARCHAR(64) NOT NULL UNIQUE,   -- SHA256(phone) for dedup lookup
    name_enc                BYTEA,

    -- Non-PII attributes
    village                 VARCHAR(200) NOT NULL,
    district                VARCHAR(100) NOT NULL DEFAULT 'Ahmedabad',
    state                   VARCHAR(50)  NOT NULL DEFAULT 'Gujarat',
    land_acres              NUMERIC(6,2),
    crops                   VARCHAR[]    NOT NULL DEFAULT '{}',  -- ['WHEAT','COTTON','GROUNDNUT']
    preferred_alert_time    TIME         DEFAULT '07:00:00',
    language                VARCHAR(10)  NOT NULL DEFAULT 'gu',

    -- Consent (DPDP Act 2023 — mandatory)
    consent_given_at        TIMESTAMPTZ,
    consent_text_version    VARCHAR(20),
    consent_channel         VARCHAR(20),   -- 'WHATSAPP', 'FIELD_AGENT'
    opt_out_at              TIMESTAMPTZ,   -- NULL = active

    -- Metadata
    is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
    onboarded_by            UUID,

    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_farmers_district
    ON farmers (district) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_farmers_active
    ON farmers (is_active, district);

COMMENT ON TABLE farmers IS
    'Farmer profiles. phone_number_enc is AES-256 encrypted. phone_hash used for dedup only.';
COMMENT ON COLUMN farmers.consent_given_at IS
    'DPDP Act 2023: explicit consent timestamp. NULL = consent not yet given.';
