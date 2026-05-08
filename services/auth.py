import os
import json
import time
import hashlib
import secrets
from typing import Optional
from fastapi import HTTPException, Header

from utils.paths import PATHS

_SESSION_TTL = int(os.getenv("SESSION_TOKEN_TTL_HOURS", "24")) * 3600


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
        salt = salt or secrets.token_hex(8)
        return hashlib.sha256((password + salt).encode()).hexdigest(), salt

    @staticmethod
    def save_auth(username, password):
        hashed, salt = AuthManager.hash_password(password)
        os.makedirs(os.path.dirname(PATHS["auth"]), exist_ok=True)
        with open(PATHS["auth"], "w") as f:
            json.dump({"username": username, "hashed": hashed, "salt": salt}, f)

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
        if authorization != f"Bearer {AuthManager._session_token}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return True
