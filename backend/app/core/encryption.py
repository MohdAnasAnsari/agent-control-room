"""
Fernet-based transparent field encryption for SQLAlchemy.

Usage in ORM models:
    system_prompt = Column(EncryptedField())
    output        = Column(EncryptedField(as_json=True))   # auto JSON ↔ str
"""

import json
import logging
from functools import lru_cache
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

import sqlalchemy.types as types

log = logging.getLogger(__name__)

# ── Key derivation ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _derive_fernet_key(encryption_key: str, secret_key: str) -> bytes:
    """
    Derive a 32-byte Fernet key from ENCRYPTION_KEY using PBKDF2-SHA256.
    Salt is the first 16 bytes of the SHA-256 hash of SECRET_KEY so it is
    deterministic (same inputs always produce the same Fernet key) without
    storing the salt in the DB.
    """
    import hashlib
    salt = hashlib.sha256(secret_key.encode()).digest()[:16]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    raw_key = kdf.derive(encryption_key.encode())
    return base64.urlsafe_b64encode(raw_key)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    from app.core.config import settings
    key_bytes = _derive_fernet_key(settings.ENCRYPTION_KEY, settings.SECRET_KEY)
    return Fernet(key_bytes)


# ── SQLAlchemy TypeDecorator ───────────────────────────────────────────────────

class EncryptedField(types.TypeDecorator):
    """
    Transparent encryption/decryption for a Text column.

    - as_json=False  → encrypts/decrypts a plain string value
    - as_json=True   → JSON-serializes before encrypting; deserializes after decrypting

    Legacy plaintext values (written before encryption was enabled) are returned
    as-is so existing data stays readable during a migration window.
    """

    impl = types.Text
    cache_ok = True

    def __init__(self, as_json: bool = False, *args: Any, **kwargs: Any) -> None:
        self.as_json = as_json
        super().__init__(*args, **kwargs)

    # ── Write path ─────────────────────────────────────────────────────────────

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if self.as_json:
            plaintext = json.dumps(value, default=str)
        elif isinstance(value, str):
            plaintext = value
        else:
            plaintext = str(value)
        token = _get_fernet().encrypt(plaintext.encode())
        return token.decode()

    # ── Read path ──────────────────────────────────────────────────────────────

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None

        # Try Fernet decryption first
        try:
            plaintext = _get_fernet().decrypt(value.encode()).decode()
            if self.as_json:
                return json.loads(plaintext)
            return plaintext
        except (InvalidToken, Exception):
            pass  # fall through to legacy handling

        # Legacy data: unencrypted value already in the column
        log.debug("EncryptedField: returning legacy unencrypted value (not a Fernet token)")
        if self.as_json:
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value
