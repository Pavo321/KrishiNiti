"""
Farmer CRUD routes.

PII handling:
- phone and name are encrypted at rest using AES-256-GCM (app.security.encryption).
- phone is also SHA-256 hashed for deduplication lookups (phone_hash column).
- FarmerResponse never includes phone or name — callers identify farmers by UUID.

Dev mode:
- If PII_ENCRYPTION_KEY is empty, store plaintext encoded as UTF-8 bytes.
  This avoids needing a real key in local development while keeping the same
  BYTEA column type.

DB pattern:
- One psycopg2 connection per request (simple, no pool complexity at this stage).
- All queries are parameterised — no string interpolation.
- Arrays (crops) are passed as Python lists; psycopg2 serialises to PG array literal.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.schemas import (
    FarmerCountResponse,
    FarmerCreate,
    FarmerResponse,
    FarmerUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/farmers", tags=["farmers"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONSENT_TEXT_VERSION = "v1.0"


def _get_conn():
    """Open a new psycopg2 connection. Caller is responsible for closing it."""
    return psycopg2.connect(settings.database_url)


def _encrypt(value: str) -> bytes:
    """Encrypt PII or fall back to UTF-8 bytes in dev mode."""
    if not settings.pii_encryption_key:
        return value.encode("utf-8")
    from app.security.encryption import encrypt_pii
    return encrypt_pii(value)


def _hash_phone(phone: str) -> str:
    from app.security.encryption import hash_phone
    return hash_phone(phone)


def _row_to_response(row: dict) -> FarmerResponse:
    return FarmerResponse(
        id=row["id"],
        village=row["village"],
        district=row["district"],
        state=row["state"],
        land_acres=float(row["land_acres"]),
        crops=list(row["crops"]),
        language=row["language"],
        is_active=row["is_active"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=FarmerResponse, status_code=201)
def register_farmer(payload: FarmerCreate) -> FarmerResponse:
    """
    Register a new farmer.

    Idempotent on phone number: if the phone hash already exists and the
    farmer is active, returns 409. If previously soft-deleted, re-activates
    the record and updates all fields.
    """
    phone_hash = _hash_phone(payload.phone)
    phone_enc = _encrypt(payload.phone)
    name_enc = _encrypt(payload.name)

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Deduplication check
                cur.execute(
                    "SELECT id, is_active FROM farmers WHERE phone_hash = %s",
                    (phone_hash,),
                )
                existing = cur.fetchone()

                if existing and existing["is_active"]:
                    raise HTTPException(
                        status_code=409,
                        detail="A farmer with this phone number is already registered.",
                    )

                if existing and not existing["is_active"]:
                    # Re-activate previously opted-out farmer
                    cur.execute(
                        """
                        UPDATE farmers SET
                            phone_number_enc = %s,
                            name_enc         = %s,
                            village          = %s,
                            district         = %s,
                            state            = %s,
                            land_acres       = %s,
                            crops            = %s,
                            language         = %s,
                            is_active        = TRUE,
                            opt_out_at       = NULL,
                            updated_at       = NOW()
                        WHERE id = %s
                        RETURNING id, village, district, state, land_acres,
                                  crops, language, is_active, created_at
                        """,
                        (
                            phone_enc,
                            name_enc,
                            payload.village,
                            payload.district,
                            payload.state,
                            payload.land_acres,
                            payload.crops,
                            payload.language,
                            existing["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO farmers (
                            phone_number_enc, phone_hash, name_enc,
                            village, district, state,
                            land_acres, crops, language,
                            consent_given_at, consent_text_version, consent_channel,
                            is_active
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            NOW(), %s, %s,
                            TRUE
                        )
                        RETURNING id, village, district, state, land_acres,
                                  crops, language, is_active, created_at
                        """,
                        (
                            phone_enc,
                            phone_hash,
                            name_enc,
                            payload.village,
                            payload.district,
                            payload.state,
                            payload.land_acres,
                            payload.crops,
                            payload.language,
                            CONSENT_TEXT_VERSION,
                            payload.consent_channel,
                        ),
                    )

                row = cur.fetchone()
                logger.info(
                    "farmer_registered",
                    extra={"farmer_id": str(row["id"]), "district": row["district"]},
                )
                return _row_to_response(row)
    finally:
        conn.close()


@router.get("/count", response_model=FarmerCountResponse)
def get_farmer_count() -> FarmerCountResponse:
    """
    Dashboard stats: total active farmers and breakdown by district.

    NOTE: this route must be declared BEFORE /{farmer_id} so FastAPI does not
    attempt to parse "count" as a UUID.
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM farmers WHERE is_active = TRUE")
            total = cur.fetchone()["total"]

            cur.execute(
                """
                SELECT district, COUNT(*) AS cnt
                FROM farmers
                WHERE is_active = TRUE
                GROUP BY district
                ORDER BY cnt DESC
                """
            )
            by_district = {row["district"]: row["cnt"] for row in cur.fetchall()}

        return FarmerCountResponse(total=total, by_district=by_district)
    finally:
        conn.close()


@router.get("", response_model=list[FarmerResponse])
def list_farmers(
    district: Optional[str] = Query(default=None, description="Filter by district name"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[FarmerResponse]:
    """List active farmers with optional district filter and pagination."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if district:
                cur.execute(
                    """
                    SELECT id, village, district, state, land_acres,
                           crops, language, is_active, created_at
                    FROM farmers
                    WHERE is_active = TRUE AND district = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (district, limit, offset),
                )
            else:
                cur.execute(
                    """
                    SELECT id, village, district, state, land_acres,
                           crops, language, is_active, created_at
                    FROM farmers
                    WHERE is_active = TRUE
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
            rows = cur.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        conn.close()


@router.get("/{farmer_id}", response_model=FarmerResponse)
def get_farmer(farmer_id: UUID) -> FarmerResponse:
    """Get a single farmer by UUID. Returns 404 if not found or soft-deleted."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, village, district, state, land_acres,
                       crops, language, is_active, created_at
                FROM farmers
                WHERE id = %s AND is_active = TRUE
                """,
                (str(farmer_id),),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Farmer not found.")
        return _row_to_response(row)
    finally:
        conn.close()


@router.patch("/{farmer_id}", response_model=FarmerResponse)
def update_farmer(farmer_id: UUID, payload: FarmerUpdate) -> FarmerResponse:
    """
    Update non-PII fields on a farmer record.

    Only columns explicitly provided in the request body are updated.
    Phone and name are not patchable here — those are PII and require
    a separate consent-aware flow.
    """
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided for update.")

    # Build SET clause dynamically from the provided fields only.
    # updated_at is always refreshed.
    allowed = {"village", "district", "state", "land_acres", "crops", "language"}
    set_clauses = []
    values = []
    for field, value in updates.items():
        if field not in allowed:
            continue
        set_clauses.append(f"{field} = %s")
        values.append(value)

    if not set_clauses:
        raise HTTPException(status_code=422, detail="No updatable fields provided.")

    set_clauses.append("updated_at = NOW()")
    values.append(str(farmer_id))

    sql = f"""
        UPDATE farmers
        SET {', '.join(set_clauses)}
        WHERE id = %s AND is_active = TRUE
        RETURNING id, village, district, state, land_acres,
                  crops, language, is_active, created_at
    """

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, values)
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Farmer not found.")
        logger.info("farmer_updated", extra={"farmer_id": str(farmer_id)})
        return _row_to_response(row)
    finally:
        conn.close()


@router.delete("/{farmer_id}", status_code=204)
def opt_out_farmer(farmer_id: UUID) -> None:
    """
    Soft-delete: marks the farmer inactive and records opt-out timestamp.

    Data is retained for regulatory/audit purposes. Phone hash is kept so
    the number cannot be re-registered without going through re-consent.
    """
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE farmers
                    SET is_active  = FALSE,
                        opt_out_at = %s,
                        updated_at = NOW()
                    WHERE id = %s AND is_active = TRUE
                    """,
                    (datetime.now(timezone.utc), str(farmer_id)),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Farmer not found.")
        logger.info("farmer_opted_out", extra={"farmer_id": str(farmer_id)})
    finally:
        conn.close()
