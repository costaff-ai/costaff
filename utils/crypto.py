import os
import json
import base64
import hashlib
import logging
from typing import Optional, Dict
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet() -> Optional[Fernet]:
    key = os.getenv("API_HEADERS_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        # The configured key isn't a valid urlsafe-base64 Fernet key.
        # Historically preflight generated `token_hex(32)` (64 hex chars),
        # which Fernet rejects -> _get_fernet() returned None and every
        # install silently stored integration headers as PLAINTEXT. Derive a
        # stable, valid Fernet key from whatever material we were given so
        # those installs start encrypting on the next write. Old plaintext
        # values still round-trip via decrypt_headers()'s plaintext fallback.
        try:
            derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
            return Fernet(derived)
        except Exception:
            logger.warning("API_HEADERS_KEY could not be derived into a Fernet key — headers stored as plaintext")
            return None


def encrypt_headers(headers: Dict) -> str:
    f = _get_fernet()
    raw = json.dumps(headers).encode()
    if f:
        return f.encrypt(raw).decode()
    else:
        logger.warning("API_HEADERS_KEY not set — headers stored as plaintext")
        return json.dumps(headers)


def decrypt_headers(encrypted: str) -> Dict:
    f = _get_fernet()
    if f:
        try:
            return json.loads(f.decrypt(encrypted.encode()).decode())
        except InvalidToken:
            pass
    try:
        return json.loads(encrypted)
    except Exception:
        return {}
