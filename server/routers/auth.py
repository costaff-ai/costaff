from fastapi import APIRouter, HTTPException

from services.auth import AuthManager
from services.audit import audit
from server.schemas import LoginRequest, SetupRequest
from utils.paths import VERSION

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@router.get("/api/check-setup")
def check_setup():
    return {"is_setup": AuthManager.get_auth() is not None}


@router.post("/api/setup")
def setup_account(req: SetupRequest):
    if AuthManager.get_auth() is not None:
        raise HTTPException(status_code=400, detail="Account already exists")
    AuthManager.save_auth(req.username, req.password)
    return {"status": "success"}


@router.post("/api/login")
def login(req: LoginRequest):
    auth = AuthManager.get_auth()
    if auth and req.username == auth["username"]:
        ok, needs_upgrade = AuthManager.verify_password(req.password, auth)
        if ok:
            if needs_upgrade:
                # Correct password on a legacy SHA-256 record — transparently
                # re-hash with the current scheme now that we hold the plaintext.
                AuthManager.save_auth(req.username, req.password)
                audit("login.hash_upgraded", username=req.username)
            token = AuthManager.rotate_token()
            audit("login.success", username=req.username)
            return {"token": token}
    audit("login.failure", username=req.username)
    raise HTTPException(status_code=401, detail="Invalid credentials")
