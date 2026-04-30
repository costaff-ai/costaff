import json
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp


@mcp.tool()
async def create_reminder_tool(
    user_id: str, session_id: str, channel: str,
    message: str, run_at: str,
    recipient: Optional[str] = None,
    app_name: str = "costaff_agent"
) -> str:
    """
    Creates a one-time reminder that sends a message to the user at run_at.
    run_at format: ISO 8601 datetime string, e.g. '2026-04-10T09:00:00'
    recipient: optional internal routing key (hashed_id). If omitted, defaults to user_id.
    For recurring scheduled agent work, use create_regular_work instead.
    """
    db = SessionLocal()
    try:
        chan = (channel or "").lower()
        if "line" in chan: chan = "line"
        elif "discord" in chan or "dc" in chan: chan = "discord"
        else: chan = "telegram"

        try:
            run_dt = datetime.fromisoformat(run_at)
        except ValueError:
            return f"Error: invalid run_at format. Use ISO 8601, e.g. '2026-04-10T09:00:00'"

        # Fallback: if LLM forgot to set recipient (or set it to a non-hashed string),
        # use user_id which is always the hashed_id by convention.
        resolved_recipient = recipient if (recipient and len(recipient) == 16) else user_id

        new_r = models.Reminder(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            app_name=app_name,
            message=message,
            run_at=run_dt,
            channel=chan,
            recipient=resolved_recipient,
            status="pending",
            created_at=datetime.utcnow()
        )
        db.add(new_r)
        db.commit()
        db.refresh(new_r)
        return f"Reminder created (ID: {new_r.id}). Will send at {run_at}."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def delete_reminder_tool(reminder_id: str) -> str:
    """Deletes a pending reminder by its ID."""
    db = SessionLocal()
    try:
        r = db.query(models.Reminder).filter(models.Reminder.id == reminder_id).first()
        if not r:
            return f"Reminder {reminder_id} not found."
        db.delete(r)
        db.commit()
        return f"Reminder {reminder_id} deleted."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_reminders_tool(user_id: str, status: Optional[str] = None) -> str:
    """Lists reminders for a user. Optionally filter by status: pending / sent / failed."""
    db = SessionLocal()
    try:
        q = db.query(models.Reminder).filter(models.Reminder.user_id == user_id)
        if status:
            q = q.filter(models.Reminder.status == status)
        items = q.order_by(models.Reminder.run_at.asc()).all()
        if not items:
            return "No reminders found."
        return json.dumps([{
            "id": r.id, "message": r.message, "run_at": r.run_at.isoformat() if r.run_at else None,
            "channel": r.channel, "status": r.status
        } for r in items], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()
