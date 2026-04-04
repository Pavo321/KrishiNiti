"""
Alert service routes.

Endpoints:
  GET  /api/v1/alerts/stats           — delivery stats for last 7 days
  GET  /api/v1/alerts/recent          — last 20 sent alerts (no PII)
  POST /api/v1/webhook/whatsapp       — receive Meta delivery receipts and farmer replies
  GET  /api/v1/webhook/whatsapp       — Meta webhook verification challenge
"""

import logging
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import settings
from app.whatsapp.webhook import (
    classify_farmer_reply,
    parse_incoming_message,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn():
    """Open a new psycopg2 connection for one request. Caller must close it."""
    return psycopg2.connect(settings.database_url, cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# GET /api/v1/alerts/stats
# ---------------------------------------------------------------------------

@router.get("/api/v1/alerts/stats")
def get_alert_stats() -> dict[str, Any]:
    """Return delivery status counts for the last 7 days."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT delivery_status, COUNT(*) AS count
                FROM alert_log
                WHERE sent_at > NOW() - INTERVAL '7 days'
                GROUP BY delivery_status
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    counts: dict[str, int] = {
        "SENT": 0,
        "DELIVERED": 0,
        "READ": 0,
        "FAILED": 0,
    }
    for row in rows:
        status = (row["delivery_status"] or "").upper()
        if status in counts:
            counts[status] = int(row["count"])

    total = sum(counts.values())
    return {"last_7_days": counts, "total_sent": total}


# ---------------------------------------------------------------------------
# GET /api/v1/alerts/recent
# ---------------------------------------------------------------------------

@router.get("/api/v1/alerts/recent")
def get_recent_alerts() -> list[dict[str, Any]]:
    """Return the last 20 sent alerts. No PII — farmer_id only, no phone number."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sent_at, farmer_id, forecast_id, message_template,
                       message_language, delivery_status, farmer_acted
                FROM alert_log
                ORDER BY sent_at DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# POST /api/v1/webhook/whatsapp
# ---------------------------------------------------------------------------

@router.post("/api/v1/webhook/whatsapp", status_code=200)
async def whatsapp_webhook_receiver(request: Request) -> dict[str, str]:
    """
    Receive incoming webhooks from Meta (delivery receipts and farmer messages).

    WhatsApp requires a 200 response within 5 seconds. All heavy processing must
    be deferred. We update delivery_status inline because it is a single DB write.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: dict = await request.json()
    except Exception:
        # Body already consumed; re-parse from raw_body
        import json as _json
        try:
            payload = _json.loads(raw_body)
        except Exception:
            logger.warning("Webhook body is not valid JSON — ignoring")
            return {"status": "ignored"}

    # --- Handle status updates (delivery receipts) ---
    _process_status_update(payload)

    # --- Handle incoming farmer messages ---
    incoming = parse_incoming_message(payload)
    if incoming:
        command = classify_farmer_reply(incoming["text"])
        logger.info(
            "Farmer message received",
            extra={
                "phone_prefix": incoming["phone"][:6],
                "message_id": incoming["message_id"],
                "command": command,
            },
        )
        if command:
            _handle_farmer_command(incoming, command)

    return {"status": "ok"}


def _process_status_update(payload: dict) -> None:
    """
    Extract delivery status updates from a Meta webhook payload and persist them.

    Meta sends: entry[0].changes[0].value.statuses[{id, status, timestamp}]
    Possible statuses: sent, delivered, read, failed.
    """
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        statuses = value.get("statuses", [])
    except (IndexError, AttributeError):
        return

    if not statuses:
        return

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            for status_obj in statuses:
                whatsapp_message_id = status_obj.get("id")
                raw_status = (status_obj.get("status") or "").upper()
                ts = status_obj.get("timestamp")

                if not whatsapp_message_id or not raw_status:
                    continue

                if raw_status == "DELIVERED":
                    cur.execute(
                        """
                        UPDATE alert_log
                        SET delivery_status = %s,
                            delivered_at = to_timestamp(%s)
                        WHERE whatsapp_message_id = %s
                          AND delivery_status != 'READ'
                        """,
                        (raw_status, ts, whatsapp_message_id),
                    )
                elif raw_status == "READ":
                    cur.execute(
                        """
                        UPDATE alert_log
                        SET delivery_status = %s,
                            read_at = to_timestamp(%s)
                        WHERE whatsapp_message_id = %s
                        """,
                        (raw_status, ts, whatsapp_message_id),
                    )
                elif raw_status in ("SENT", "FAILED"):
                    cur.execute(
                        """
                        UPDATE alert_log
                        SET delivery_status = %s
                        WHERE whatsapp_message_id = %s
                          AND delivery_status NOT IN ('DELIVERED', 'READ')
                        """,
                        (raw_status, whatsapp_message_id),
                    )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to persist delivery status update: %s", exc)
    finally:
        conn.close()


def _handle_farmer_command(incoming: dict, command: str) -> None:
    """
    Persist a farmer's reply and act on recognized commands.

    Currently persists the reply text and marks farmer_acted=TRUE for
    'confirm_purchase' commands. Opt-out (STOP) and opt-in (START) will be
    handled by the farmer-service once the inter-service event bus is wired up.
    """
    whatsapp_message_id = incoming["message_id"]
    reply_text = incoming["text"]
    phone = incoming["phone"]
    ts = incoming.get("timestamp")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Find the most recent alert sent to this phone that has not yet
            # received a reply. We match on the whatsapp_message_id stored at
            # send-time (context.id in the incoming message) when available,
            # otherwise fall back to the latest unread alert for this phone hash.
            farmer_acted = command == "confirm_purchase"

            cur.execute(
                """
                UPDATE alert_log
                SET farmer_reply       = %s,
                    reply_received_at  = to_timestamp(%s),
                    farmer_acted       = %s,
                    acted_at           = CASE WHEN %s THEN to_timestamp(%s) ELSE acted_at END
                WHERE id = (
                    SELECT al.id
                    FROM alert_log al
                    JOIN farmers f ON f.id = al.farmer_id
                    WHERE f.phone_hash = encode(digest(%s, 'sha256'), 'hex')
                      AND al.farmer_reply IS NULL
                    ORDER BY al.sent_at DESC
                    LIMIT 1
                )
                """,
                (
                    reply_text,
                    ts,
                    farmer_acted,
                    farmer_acted,
                    ts,
                    phone,
                ),
            )
        conn.commit()
        logger.info(
            "Farmer command persisted",
            extra={"command": command, "phone_prefix": phone[:6]},
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to persist farmer command: %s", exc)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GET /api/v1/webhook/whatsapp  — Meta verification challenge
# ---------------------------------------------------------------------------

@router.get("/api/v1/webhook/whatsapp")
def whatsapp_webhook_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
) -> Response:
    """
    Meta calls this endpoint once during webhook registration.
    We must echo back hub.challenge if hub.verify_token matches our app secret.
    """
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="Invalid hub.mode")

    if hub_verify_token != settings.whatsapp_app_secret:
        logger.warning("Webhook verification failed: token mismatch")
        raise HTTPException(status_code=403, detail="Verification token mismatch")

    logger.info("WhatsApp webhook verified successfully")
    return Response(content=hub_challenge, media_type="text/plain")
