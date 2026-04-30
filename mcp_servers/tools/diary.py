import json
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp, tz


@mcp.tool()
async def write_diary(
    user_id: str, agent_name: str, date: str,
    done: str, next: str,
    blocker: Optional[str] = None,
    ref_task_ids: Optional[list] = None,
    diary_type: str = "daily"
) -> str:
    """
    Writes a diary entry for an Agent (standup format).
    - date: YYYY-MM-DD
    - done: what was completed today
    - next: planned actions for tomorrow
    - blocker: any issues encountered (omit if none)
    - ref_task_ids: list of related ProjectTask IDs
    - diary_type: daily / weekly / monthly
    Overwrites existing entry for the same agent + date + type.
    """
    db = SessionLocal()
    try:
        # Upsert: overwrite if same agent+date+type exists
        existing = db.query(models.Diary).filter(
            models.Diary.user_id == user_id,
            models.Diary.agent_name == agent_name,
            models.Diary.date == date,
            models.Diary.type == diary_type
        ).first()

        ref_json = json.dumps(ref_task_ids or [], ensure_ascii=False)

        if existing:
            existing.done = done
            existing.next = next
            existing.blocker = blocker
            existing.ref_task_ids = ref_json
        else:
            entry = models.Diary(
                id=str(uuid.uuid4()),
                user_id=user_id,
                agent_name=agent_name,
                date=date,
                type=diary_type,
                done=done,
                blocker=blocker,
                next=next,
                ref_task_ids=ref_json,
                created_at=datetime.utcnow()
            )
            db.add(entry)

        db.commit()
        return f"Diary entry written for {agent_name} on {date}."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_diary(user_id: str, date: str) -> str:
    """
    Returns all Agent diary entries for a specific date (YYYY-MM-DD).
    Shows the full team standup for that day.
    """
    db = SessionLocal()
    try:
        entries = db.query(models.Diary).filter(
            models.Diary.user_id == user_id,
            models.Diary.date == date,
            models.Diary.type == "daily"
        ).order_by(models.Diary.agent_name.asc()).all()
        if not entries:
            return f"No diary entries found for {date}."
        return json.dumps([{
            "agent": e.agent_name, "date": e.date,
            "done": e.done, "blocker": e.blocker, "next": e.next,
            "ref_task_ids": json.loads(e.ref_task_ids or "[]")
        } for e in entries], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_recent_diaries(user_id: str, days: int = 3) -> str:
    """
    Returns diary entries for the last N days (default 3), all agents combined.
    Use this at the start of a conversation to get recent team context.
    """
    db = SessionLocal()
    try:
        from sqlalchemy import desc
        entries = (
            db.query(models.Diary)
            .filter(
                models.Diary.user_id == user_id,
                models.Diary.type == "daily"
            )
            .order_by(desc(models.Diary.date), models.Diary.agent_name.asc())
            .limit(days * 10)  # Up to 10 agents per day
            .all()
        )
        if not entries:
            return "No recent diary entries found."
        return json.dumps([{
            "date": e.date, "agent": e.agent_name,
            "done": e.done, "blocker": e.blocker, "next": e.next
        } for e in entries], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()
