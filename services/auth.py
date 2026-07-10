import os
import json
import time
import hashlib
import hmac
import secrets
from typing import Optional
from fastapi import HTTPException, Header

from utils.paths import PATHS

_SESSION_TTL = int(os.getenv("SESSION_TOKEN_TTL_HOURS", "24")) * 3600

# PBKDF2-HMAC-SHA256 — stdlib, no extra dependency. 600k iterations matches
# the current OWASP guidance for PBKDF2-SHA256. Single-round SHA-256 (the
# previous scheme) is near-free to brute-force on a GPU if auth.json leaks.
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000


class AuthManager:
    _session_token: str = ""
    _token_expires: float = 0.0

    @classmethod
    def rotate_token(cls) -> str:
        """Generate a new session token and set its expiry. Returns the new token."""
        cls._session_token = secrets.token_hex(16)
        cls._token_expires = time.time() + _SESSION_TTL
        return cls._session_token

    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None):
        """Hash a password with PBKDF2-HMAC-SHA256. Returns (hash_hex, salt).

        Kept as a 2-tuple for backward compatibility with existing callers.
        """
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
        )
        return digest.hex(), salt

    @staticmethod
    def _legacy_sha256(password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode()).hexdigest()

    @staticmethod
    def verify_password(password: str, auth: dict) -> tuple[bool, bool]:
        """Check `password` against a stored auth record.

        Returns (ok, needs_upgrade). `needs_upgrade` is True when the stored
        record used the legacy single-round SHA-256 scheme and the caller
        should re-save with the current algorithm. All comparisons are
        constant-time.
        """
        salt = auth.get("salt", "")
        stored = auth.get("hashed", "")
        if auth.get("algo") == _PBKDF2_ALGO:
            iterations = int(auth.get("iterations", _PBKDF2_ITERATIONS))
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), iterations
            ).hex()
            return hmac.compare_digest(digest, stored), False
        # No algo marker → legacy SHA-256. Verify, then flag for upgrade.
        ok = hmac.compare_digest(AuthManager._legacy_sha256(password, salt), stored)
        return ok, ok

    @staticmethod
    def save_auth(username, password):
        hashed, salt = AuthManager.hash_password(password)
        os.makedirs(os.path.dirname(PATHS["auth"]), exist_ok=True)
        with open(PATHS["auth"], "w") as f:
            json.dump({
                "username": username,
                "hashed": hashed,
                "salt": salt,
                "algo": _PBKDF2_ALGO,
                "iterations": _PBKDF2_ITERATIONS,
            }, f)

    @staticmethod
    def get_auth():
        if os.path.exists(PATHS["auth"]):
            try:
                with open(PATHS["auth"], "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    @staticmethod
    def verify_token(authorization: str = Header(None)):
        if not AuthManager._session_token:
            raise HTTPException(status_code=401, detail="Not logged in")
        if time.time() > AuthManager._token_expires:
            raise HTTPException(status_code=401, detail="Session expired, please log in again")
        # Constant-time compare — the token is the sole bearer credential.
        expected = f"Bearer {AuthManager._session_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return True
