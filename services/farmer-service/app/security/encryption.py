"""
PII field-level encryption for farmer data.
Uses AES-256-GCM via the cryptography library.
Even DB admins cannot read raw phone numbers or names.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Load AES-256 key from environment. Key is base64-encoded 32 bytes."""
    key_b64 = os.environ.get("PII_ENCRYPTION_KEY", "")
    if not key_b64:
        raise RuntimeError(
            "PII_ENCRYPTION_KEY not set. "
            "Generate with: python -c \"import os,base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError(f"PII_ENCRYPTION_KEY must be 32 bytes. Got {len(key)} bytes.")
    return key


def encrypt_pii(plaintext: str) -> bytes:
    """
    Encrypts PII string using AES-256-GCM.
    Returns: nonce (12 bytes) + ciphertext + tag (16 bytes), as bytes.
    Each encryption uses a fresh random nonce — same plaintext produces different ciphertext.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_pii(encrypted: bytes) -> str:
    """Decrypts AES-256-GCM encrypted PII. Raises if tampered."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def hash_phone(phone_number: str) -> str:
    """
    One-way SHA-256 hash of phone number for deduplication lookups.
    Used as unique constraint — not for retrieval of the actual number.
    Normalize to E.164 format before hashing.
    """
    normalized = phone_number.strip().replace(" ", "").replace("-", "")
    if not normalized.startswith("+"):
        normalized = "+91" + normalized   # default to India
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
