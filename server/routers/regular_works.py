"""Regular Works endpoints — cron-scheduled recurring jobs.

Each `regular_work` row defines a cron expression and a spec string sent
to an agent on schedule. Decoupled from the project Epic/Story/Task
hierarchy because regular works run autonomously and do not produce
per-run artifacts (their effect is the side-effects each agent run has).
"""
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from services.audit import audit
from services.auth import AuthManager
from services.database import DatabaseManager
from server.schemas import RegularWorkCreateRequest, RegularWorkUpdateRequest
from utils.serialization import _serialize_row
from utils.validators import _validate_cron

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_targets(req) -> list:
    """Collapse the request's channel fields into [{"channel", "recipient"}].

    Prefers the multi-channel `channels` list; falls back to the legacy
    single channel/recipient pair so old API clients keep working.
    """
    if req.channels is not None:
        return [
            {"channel": t.channel.strip(), "recipient": (t.recipient or "").strip() or None}
            for t in req.channels if t.channel and t.channel.strip()
        ]
    if req.channel:
        return [{"channel": req.channel, "recipient": req.recipient}]
    return []


def _target_columns(targets: list) -> dict:
    """DB values for a target list: JSON blob + legacy mirror of the first pair."""
    first = targets[0] if targets else {}
    return {
        "channels": json.dumps(targets, ensure_ascii=False) if targets else None,
        "channel": first.get("channel"),
        "recipient": first.get("recipient"),
    }


def _parse_targets_row(row: dict) -> dict:
    """Decode the channels JSON column into a list for API responses."""
    raw = row.pop("channels", None)
    targets = None
    if raw:
        try:
            targets = [t for t in json.loads(raw) if isinstance(t, dict) and t.get("channel")]
        except (ValueError, TypeError):
            targets = None
    if targets is None:
        targets = [{"channel": row["channel"], "recipient": row.get("recipient")}] if row.get("channel") else []
    row["channels"] = targets
    return row


@router.get("/api/regular-works")
def list_regular_works(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    base_cols = ("id, user_id, title, spec, cron, agent_id, channel, recipient, "
                 "status, last_run, next_run, created_at, updated_at")
    try:
        with engine.connect() as conn:
            try:
                res = conn.execute(text(
                    f"SELECT {base_cols}, channels FROM regular_works ORDER BY created_at ASC"
                ))
                rows = [dict(r._mapping) for r in res]
            except Exception:
                # Stack DB not migrated to 0002 yet — fall back to legacy columns.
                conn.rollback()
                res = conn.execute(text(
                    f"SELECT {base_cols} FROM regular_works ORDER BY created_at ASC"
                ))
                rows = [dict(r._mapping) for r in res]
            return [_parse_targets_row(_serialize_row(r)) for r in rows]
    except Exception:
        logger.exception("regular_works list-handler failed")
        return []


@router.post("/api/regular-works")
def create_regular_work_api(req: RegularWorkCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    try:
        _validate_cron(req.cron)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        wid = str(uuid.uuid4())
        now = datetime.utcnow()
        cols = _target_columns(_normalize_targets(req))
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO regular_works (id, user_id, session_id, title, spec, cron, agent_id, channel, recipient, channels, status, created_at, updated_at)
                VALUES (:id, :user_id, :session_id, :title, :spec, :cron, :agent_id, :channel, :recipient, :channels, :status, :now, :now)
            """), {
                "id": wid, "user_id": req.user_id or "dashboard-user",
                "session_id": "dashboard-manual", "title": req.title,
                "spec": req.spec, "cron": req.cron, "agent_id": req.agent_id or "costaff_agent",
                "channel": cols["channel"], "recipient": cols["recipient"], "channels": cols["channels"],
                "status": "active", "now": now
            })
            conn.commit()
        audit("work.create", id=wid, title=req.title, cron=req.cron)
        return {"status": "success", "id": wid}
    except Exception as e:
        logger.exception("regular_works router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/regular-works/{work_id}")
def update_regular_work_api(work_id: str, req: RegularWorkUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    if req.cron is not None:
        try:
            _validate_cron(req.cron)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        updates = req.dict(exclude_unset=True)
        if not updates:
            return {"status": "no changes"}
        if "channels" in updates or "channel" in updates or "recipient" in updates:
            # Any channel-shaped edit rewrites the full target set (JSON +
            # legacy mirror) so the two representations never diverge.
            updates.update(_target_columns(_normalize_targets(req)))
        updates["id"] = work_id
        updates["now"] = datetime.utcnow()
        allowed = {"title", "spec", "cron", "agent_id", "channel", "recipient", "channels", "status"}
        set_clauses = [f"{k} = :{k}" for k in updates if k in allowed]
        set_clauses.append("updated_at = :now")
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE regular_works SET {', '.join(set_clauses)} WHERE id = :id"), updates)
            conn.commit()
        audit("work.update", id=work_id, changes={k: v for k, v in updates.items() if k not in ("id", "now")})
        return {"status": "success"}
    except Exception as e:
        logger.exception("regular_works router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/regular-works/{work_id}")
def delete_regular_work_api(work_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM regular_works WHERE id = :id"), {"id": work_id})
            conn.commit()
        audit("work.delete", id=work_id)
        return {"status": "success"}
    except Exception as e:
        logger.exception("regular_works router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/regular-works/{work_id}/toggle")
def toggle_regular_work(work_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT status FROM regular_works WHERE id = :id"), {"id": work_id}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Not found")
            new_status = "paused" if row[0] == "active" else "active"
            conn.execute(text("UPDATE regular_works SET status = :s, updated_at = :now WHERE id = :id"),
                         {"s": new_status, "now": datetime.utcnow(), "id": work_id})
            conn.commit()
        return {"status": "success", "new_status": new_status}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("regular_works router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/regular-works/{work_id}/logs")
def get_regular_work_logs(work_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(
                "SELECT id, status, output, created_at FROM regular_work_logs "
                "WHERE regular_work_id = :id ORDER BY created_at DESC LIMIT 50"
            ), {"id": work_id})
            return [_serialize_row(dict(r._mapping)) for r in res]
    except Exception:
        logger.exception("regular_works list-handler failed")
        return []
