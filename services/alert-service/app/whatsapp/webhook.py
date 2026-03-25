"""
WhatsApp webhook receiver with HMAC-SHA256 signature verification.
Security: every incoming request is verified before processing.
"""

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature_header: str) -> bool:
    """
    Verifies Meta's webhook signature.
    Meta sends: X-Hub-Signature-256: sha256=<hex_digest>
    We compute HMAC-SHA256(app_secret, payload) and compare.
    Timing-safe comparison prevents timing attacks.
    """
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not app_secret:
        logger.error("WHATSAPP_APP_SECRET not set. Cannot verify webhook.")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Webhook signature missing sha256= prefix. Rejecting.")
        return False

    received_sig = signature_header[7:]   # strip "sha256="
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_sig, received_sig)
    if not is_valid:
        logger.warning("Webhook signature mismatch. Possible spoofed request.")
    return is_valid


def parse_incoming_message(payload: dict) -> dict | None:
    """
    Parses a WhatsApp webhook payload to extract farmer message.
    Returns None if not a text message from a farmer.
    """
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return None

        msg = messages[0]
        if msg.get("type") != "text":
            return None

        return {
            "phone": msg["from"],
            "message_id": msg["id"],
            "text": msg["text"]["body"].strip().upper(),
            "timestamp": msg["timestamp"],
        }
    except (KeyError, IndexError):
        return None


FARMER_COMMANDS = {
    "STOP": "opt_out",
    "START": "opt_in",
    "WRONG": "wrong_prediction",
    "BOUGHT": "confirm_purchase",
}


def classify_farmer_reply(text: str) -> str | None:
    """Returns command type or None if not a recognized command."""
    for keyword, command in FARMER_COMMANDS.items():
        if keyword in text.upper():
            return command
    return None
