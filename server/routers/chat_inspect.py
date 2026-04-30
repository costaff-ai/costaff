"""Chat session + raw DB inspection endpoints — backs the dashboard's
"Sessions" and "Database" debug views.

These endpoints are read-only and intended for operator inspection of
historical state. The `/api/db/{table}` endpoint is a generic table
viewer with a hard-coded allow-list of table names and columns; do not
expose untrusted user input to it.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from services.auth import AuthManager
from services.database import DatabaseManager

router = APIRouter()


@router.get("/api/chat/sessions")
def get_chat_sessions(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text('SELECT id, user_id, app_name, "update_time" FROM sessions ORDER BY "update_time" DESC'))
            return [dict(row._mapping) for row in res]
    except Exception:
        import traceback
        traceback.print_exc()
        return []


@router.get("/api/chat/history/{session_id}")
def get_chat_history(session_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text('SELECT event_data, "timestamp" FROM events WHERE session_id = :sid ORDER BY "timestamp" ASC'), {"sid": session_id})
            rows = []
            for row in res:
                ed = row[0]
                if isinstance(ed, str):
                    ed = json.loads(ed)
                ts = row[1].timestamp() if isinstance(row[1], datetime) else float(row[1])
                rows.append({"event_data": ed, "timestamp": ts})
            return rows
    except Exception:
        import traceback
        traceback.print_exc()
        return []


_TABLE_QUERIES = {
    "identities": "SELECT session_id, hashed_id, real_id, created_at FROM identity_maps ORDER BY created_at DESC",
    "profiles": "SELECT user_id, chinese_name, job_title, company_name, personal_email, mobile_phone, employee_id, note FROM user_contacts",
    "reminders": "SELECT id, user_id, message, run_at, channel, recipient, status, created_at FROM reminders ORDER BY created_at DESC LIMIT 100",
    "events": "SELECT id, session_id, event_data, timestamp FROM events ORDER BY timestamp DESC LIMIT 200",
    "user_states": "SELECT app_name, user_id, state, update_time FROM user_states",
}


def _simplify_event_parts(raw_parts: list) -> list:
    """Reduce raw ADK event parts to a compact form the dashboard can render."""
    simplified = []
    for p in raw_parts:
        if "text" in p:
            simplified.append({"type": "text", "text": p["text"][:800]})
        elif "function_call" in p:
            fc = p["function_call"]
            simplified.append({"type": "call", "name": fc.get("name", ""), "args": fc.get("args", {})})
        elif "functionCall" in p:  # legacy camelCase fallback
            fc = p["functionCall"]
            simplified.append({"type": "call", "name": fc.get("name", ""), "args": fc.get("args", {})})
        elif "function_response" in p:
            fr = p["function_response"]
            resp = fr.get("response", {})
            content = resp.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            data = resp.get("structuredContent") or content or ""
            simplified.append({"type": "result", "name": fr.get("name", ""), "data": data})
        elif "functionResponse" in p:  # legacy camelCase fallback
            fr = p["functionResponse"]
            resp = fr.get("response", {})
            content = resp.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            data = resp.get("structuredContent") or content or ""
            simplified.append({"type": "result", "name": fr.get("name", ""), "data": data})
    return simplified


@router.get("/api/db/{table}")
def get_db_table_data(table: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    if table not in _TABLE_QUERIES:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(_TABLE_QUERIES[table]))
            rows = []
            for row in res:
                d = dict(row._mapping)
                for k, v in d.items():
                    if isinstance(v, datetime):
                        # Force UTC marker 'Z' so the frontend browser can convert to local timezone
                        if v.tzinfo is None:
                            d[k] = v.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        else:
                            d[k] = v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if table == "events" and "event_data" in d:
                    ed = d["event_data"]
                    if isinstance(ed, str):
                        ed = json.loads(ed)
                    d["author"] = ed.get("author", "unknown")
                    raw_parts = ed.get("content", {}).get("parts", [])
                    simplified = _simplify_event_parts(raw_parts)
                    if not simplified:
                        continue  # Skip events with no meaningful content
                    d["content"] = json.dumps(simplified, ensure_ascii=False)
                rows.append(d)
            return rows
    except Exception:
        return []
