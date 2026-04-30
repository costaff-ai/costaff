"""External integrations: user-defined API configs + Skill registry CRUD.

These are the two `*_configs` tables agents consult at runtime to
discover external HTTP APIs and reusable skill descriptors. Both are
agent-facing config (lookup is the hot path), so the dashboard CRUD
here is operator tooling — read/write throughput is low.

API configs encrypt their `headers` field with utils.crypto so the
list endpoint only reveals the header *key names*, never values.
"""
import sys
import uuid
from datetime import datetime, datetime as _dt, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.auth import AuthManager
from services.database import DatabaseManager
from server.schemas import (
    ApiConfigCreateRequest, ApiConfigUpdateRequest,
    SkillConfigCreateRequest, SkillConfigUpdateRequest,
)
from utils.crypto import encrypt_headers, decrypt_headers
from utils.network import is_safe_url
from utils.helpers import _project_root

router = APIRouter()


# ---------------------------------------------------------------------------
# API configs
# ---------------------------------------------------------------------------

@router.get("/api/apis")
def list_api_configs(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text("SELECT id, name, url, method, headers_encrypted, description, user_id, agent_ids, is_active, created_at FROM api_configs ORDER BY created_at DESC"))
            rows = []
            for row in res:
                d = dict(row._mapping)
                # Expose only header key names, not values
                if d.get("headers_encrypted"):
                    try:
                        h = decrypt_headers(d["headers_encrypted"])
                        d["header_keys"] = list(h.keys())
                    except Exception:
                        d["header_keys"] = []
                else:
                    d["header_keys"] = []
                del d["headers_encrypted"]
                if isinstance(d.get("created_at"), datetime):
                    d["created_at"] = d["created_at"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                rows.append(d)
            return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/apis")
def create_api_config(req: ApiConfigCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    if not is_safe_url(req.url):
        raise HTTPException(status_code=400, detail="URL resolves to a private/reserved IP address (SSRF protection).")
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        new_id = str(uuid.uuid4())
        headers_enc = encrypt_headers(req.headers) if req.headers else None
        effective_user_id = req.user_id or "__global__"
        effective_agent_ids = req.agent_ids or "__all__"
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO api_configs (id, name, url, method, headers_encrypted, description, user_id, agent_ids, is_active, created_at, updated_at)
                VALUES (:id, :name, :url, :method, :headers_encrypted, :description, :user_id, :agent_ids, :is_active, :now, :now)
            """), {
                "id": new_id, "name": req.name, "url": req.url, "method": req.method.upper(),
                "headers_encrypted": headers_enc, "description": req.description,
                "user_id": effective_user_id, "agent_ids": effective_agent_ids,
                "is_active": True, "now": _dt.utcnow()
            })
            conn.commit()
        return {"status": "success", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/apis/{api_id}")
def update_api_config(api_id: str, req: ApiConfigUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    if req.url and not is_safe_url(req.url):
        raise HTTPException(status_code=400, detail="URL resolves to a private/reserved IP address (SSRF protection).")
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        updates: Dict[str, Any] = {"id": api_id, "now": _dt.utcnow()}
        if req.name is not None: updates["name"] = req.name
        if req.url is not None: updates["url"] = req.url
        if req.method is not None: updates["method"] = req.method.upper()
        if req.headers is not None: updates["headers_encrypted"] = encrypt_headers(req.headers)
        if req.description is not None: updates["description"] = req.description
        if req.is_active is not None: updates["is_active"] = req.is_active
        if req.agent_ids is not None: updates["agent_ids"] = req.agent_ids
        set_clauses = [f"{k} = :{k}" for k in updates if k not in ("id", "now")]
        set_clauses.append("updated_at = :now")
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE api_configs SET {', '.join(set_clauses)} WHERE id = :id"), updates)
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/apis/{api_id}")
def delete_api_config(api_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM api_configs WHERE id = :id"), {"id": api_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Skill configs
# ---------------------------------------------------------------------------

@router.get("/api/skills")
def list_skill_configs(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text("SELECT id, name, description, tags, usage, user_id, agent_ids, is_active, created_at FROM skill_configs ORDER BY created_at DESC"))
            rows = []
            for row in res:
                d = dict(row._mapping)
                if isinstance(d.get("created_at"), datetime):
                    d["created_at"] = d["created_at"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                rows.append(d)
            return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/skills")
def create_skill_config(req: SkillConfigCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        sys.path.insert(0, _project_root)
        from core.license import LicenseManager
        with Session(engine) as _s:
            LicenseManager.check_skill_limit(_s)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    try:
        new_id = str(uuid.uuid4())
        effective_user_id = req.user_id or "__global__"
        effective_agent_ids = req.agent_ids or "__all__"
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO skill_configs (id, name, description, tags, usage, user_id, agent_ids, is_active, created_at, updated_at)
                VALUES (:id, :name, :description, :tags, :usage, :user_id, :agent_ids, :is_active, :now, :now)
            """), {
                "id": new_id, "name": req.name, "description": req.description,
                "tags": req.tags, "usage": req.usage, "user_id": effective_user_id,
                "agent_ids": effective_agent_ids, "is_active": True, "now": _dt.utcnow()
            })
            conn.commit()
        return {"status": "success", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/skills/{skill_id}")
def update_skill_config(skill_id: str, req: SkillConfigUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        updates = {}
        if req.name is not None: updates["name"] = req.name
        if req.description is not None: updates["description"] = req.description
        if req.tags is not None: updates["tags"] = req.tags
        if req.usage is not None: updates["usage"] = req.usage
        if req.is_active is not None: updates["is_active"] = req.is_active
        if req.agent_ids is not None: updates["agent_ids"] = req.agent_ids
        if not updates: return {"status": "success"}
        updates["updated_at"] = _dt.utcnow()
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = skill_id
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE skill_configs SET {set_clause} WHERE id = :id"), updates)
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/skills/{skill_id}")
def delete_skill_config(skill_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM skill_configs WHERE id = :id"), {"id": skill_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
