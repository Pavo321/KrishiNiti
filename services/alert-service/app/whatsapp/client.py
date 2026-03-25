"""
WhatsApp Business API client (Meta Cloud API).
Handles message sending and delivery status updates.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

WHATSAPP_API_VERSION = "v19.0"
WHATSAPP_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


class WhatsAppClient:
    def __init__(self):
        self.token = os.environ["WHATSAPP_API_TOKEN"]
        self.phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self.base_url = f"{WHATSAPP_BASE_URL}/{self.phone_number_id}"

    def send_text_message(self, to_phone: str, message: str) -> dict:
        """
        Sends a plain text WhatsApp message.
        to_phone: E.164 format, e.g., "+919876543210"
        Returns: WhatsApp API response with message_id.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message,
            },
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=headers,
            )

        if response.status_code != 200:
            logger.error(
                f"WhatsApp API error {response.status_code}: {response.text[:200]}"
            )
            response.raise_for_status()

        result = response.json()
        message_id = result.get("messages", [{}])[0].get("id", "")
        logger.info(f"Message sent to {to_phone[:6]}****, message_id: {message_id}")
        return result

    def mark_message_read(self, message_id: str) -> None:
        """Marks an incoming message as read (shows double blue tick to farmer)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        headers = {"Authorization": f"Bearer {self.token}"}
        with httpx.Client(timeout=10) as client:
            client.post(f"{self.base_url}/messages", json=payload, headers=headers)
