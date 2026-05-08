"""Identity & user lifecycle endpoints — backs the dashboard's user-management views.

Covers:
  - Listing user profiles and their identity-map entries
  - Approving / revoking / deleting a session's identity
  - Hard-deleting a user (and ad-hoc cleanup of their state and reminders)
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from services.auth import AuthManager
from services.database import DatabaseManager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/users")
def get_users(auth: bool = Depends(AuthManager.verify_token)):
    """Returns user profiles (no approval logic here)."""
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT user_id, chinese_name, english_name, job_title, company_name, "
                "personal_email, mobile_phone FROM user_contacts ORDER BY chinese_name"
            ))
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.exception("get_users failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/identities")
def get_identities(auth: bool = Depends(AuthManager.verify_token)):
    """Returns identity map entries joined with profile name."""
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            # Check if webchat_users table exists
            check_table = conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'webchat_users')"))
            has_webchat = check_table.scalar()

            if has_webchat:
                sql = """
                    SELECT i.session_id, i.hashed_id, i.real_id, i.is_approved, i.created_at,
                           COALESCE(u.chinese_name, u.english_name, w.username) AS name
                    FROM identity_maps i
                    LEFT JOIN user_contacts u ON u.user_id = i.hashed_id
                    LEFT JOIN webchat_users w ON i.session_id LIKE 'web_%%' AND w.email = i.real_id
                    ORDER BY i.created_at DESC
                """
            else:
                sql = """
                    SELECT i.session_id, i.hashed_id, i.real_id, i.is_approved, i.created_at,
                           COALESCE(u.chinese_name, u.english_name) AS name
                    FROM identity_maps i
                    LEFT JOIN user_contacts u ON u.user_id = i.hashed_id
                    ORDER BY i.created_at DESC
                """

            rows = conn.execute(text(sql))
            result = []
            for row in rows:
                d = dict(row._mapping)
                if isinstance(d.get("created_at"), datetime):
                    d["created_at"] = d["created_at"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                result.append(d)
            return result
    except Exception as e:
        logger.exception("get_identities failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/identities/{session_id}/approve")
def approve_identity(session_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database unavailable")
    with engine.connect() as conn:
        conn.execute(text("UPDATE identity_maps SET is_approved = true WHERE session_id = :sid"), {"sid": session_id})
        conn.commit()
    return {"status": "approved"}


@router.post("/api/identities/{session_id}/revoke")
def revoke_identity(session_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database unavailable")
    with engine.connect() as conn:
        conn.execute(text("UPDATE identity_maps SET is_approved = false WHERE session_id = :sid"), {"sid": session_id})
        conn.commit()
    return {"status": "revoked"}


@router.delete("/api/identities/{session_id}")
def delete_identity(session_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database unavailable")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM identity_maps WHERE session_id = :sid"), {"sid": session_id})
        conn.commit()
    return {"status": "deleted"}


@router.delete("/api/memory/user_states")
def delete_user_state(app_name: str, user_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database unavailable")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM user_states WHERE app_name = :a AND user_id = :u"), {"a": app_name, "u": user_id})
        conn.commit()
    return {"status": "deleted"}


@router.delete("/api/users/{user_id}")
def delete_user(user_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database unavailable")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM user_contacts WHERE user_id = :uid"), {"uid": user_id})
        conn.commit()
    return {"status": "deleted"}


@router.delete("/api/reminders/{reminder_id}")
def delete_reminder(reminder_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM reminders WHERE id = :rid"), {"rid": reminder_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("delete_reminder failed for reminder_id=%s", reminder_id)
        raise HTTPException(status_code=500, detail=str(e))
