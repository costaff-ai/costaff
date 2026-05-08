import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp, scheduler, scheduled_job_ids



logger = logging.getLogger(__name__)
@mcp.tool()
async def create_regular_work(
    user_id: str, session_id: str,
    title: str, spec: str, cron: str,
    channel: Optional[str] = None, recipient: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Creates a recurring scheduled job delegated to an Agent.
    Use this for any recurring automated work (e.g. daily news summary, weekly report).
    - cron: 5-part cron expression, e.g. '0 9 * * *' for every day at 09:00
    - agent_id: which agent to call (default: costaff_agent)
    - spec: full instructions for the agent
    """
    db = SessionLocal()
    try:
        # Fallback: if LLM passed a non-hashed string as recipient (e.g. a display
        # name), normalize to user_id so the IdentityMap lookup succeeds at execution.
        resolved_recipient = recipient if (recipient and len(recipient) == 16) else (recipient or None)
        if recipient and len(recipient) != 16:
            resolved_recipient = user_id

        new_w = models.RegularWork(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            title=title,
            spec=spec,
            cron=cron,
            agent_id=agent_id,
            channel=channel,
            recipient=resolved_recipient,
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_w)
        db.commit()
        db.refresh(new_w)
        return f"Regular work '{title}' created (ID: {new_w.id}), schedule: {cron}."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_regular_work(
    regular_work_id: str,
    title: Optional[str] = None,
    spec: Optional[str] = None,
    cron: Optional[str] = None,
    agent_id: Optional[str] = None,
    channel: Optional[str] = None,
    recipient: Optional[str] = None
) -> str:
    """Updates fields of an existing regular work entry."""
    db = SessionLocal()
    try:
        w = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not w:
            return f"Regular work {regular_work_id} not found."
        if title is not None: w.title = title
        if spec is not None: w.spec = spec
        if cron is not None:
            w.cron = cron
            # Remove old scheduler job so it gets re-added with new cron
            job_id = f"rwork_{w.id}"
            try:
                scheduler.remove_job(job_id)
                scheduled_job_ids.discard(job_id)
            except Exception:
                pass
        if agent_id is not None: w.agent_id = agent_id
        if channel is not None: w.channel = channel
        if recipient is not None: w.recipient = recipient
        w.updated_at = datetime.utcnow()
        db.commit()
        return f"Regular work {regular_work_id} updated."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def pause_regular_work(regular_work_id: str) -> str:
    """Pauses a regular work so it stops running on schedule."""
    db = SessionLocal()
    try:
        w = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not w:
            return f"Regular work {regular_work_id} not found."
        w.status = "paused"
        w.updated_at = datetime.utcnow()
        db.commit()
        job_id = f"rwork_{w.id}"
        try:
            scheduler.remove_job(job_id)
            scheduled_job_ids.discard(job_id)
        except Exception:
            pass
        return f"Regular work '{w.title}' paused."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def resume_regular_work(regular_work_id: str) -> str:
    """Resumes a paused regular work."""
    db = SessionLocal()
    try:
        w = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not w:
            return f"Regular work {regular_work_id} not found."
        w.status = "active"
        w.updated_at = datetime.utcnow()
        db.commit()
        return f"Regular work '{w.title}' resumed. Will sync to scheduler within 30s."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def delete_regular_work(regular_work_id: str) -> str:
    """Permanently deletes a regular work entry."""
    db = SessionLocal()
    try:
        w = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not w:
            return f"Regular work {regular_work_id} not found."
        db.delete(w)
        db.commit()
        job_id = f"rwork_{regular_work_id}"
        try:
            scheduler.remove_job(job_id)
            scheduled_job_ids.discard(job_id)
        except Exception:
            pass
        return f"Regular work {regular_work_id} deleted."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_regular_works(user_id: str, status: Optional[str] = None) -> str:
    """
    Lists all regular works for a user.
    - status: optional filter — 'active' or 'paused'
    """
    db = SessionLocal()
    try:
        q = db.query(models.RegularWork).filter(models.RegularWork.user_id == user_id)
        if status:
            q = q.filter(models.RegularWork.status == status)
        items = q.order_by(models.RegularWork.created_at.desc()).all()
        if not items:
            return "No regular works found."
        return json.dumps([{
            "id": w.id, "title": w.title, "cron": w.cron,
            "agent_id": w.agent_id, "status": w.status,
            "last_run": w.last_run.isoformat() if w.last_run else None
        } for w in items], ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_regular_work_logs(regular_work_id: str, limit: int = 10) -> str:
    """Returns the last N execution logs for a regular work."""
    db = SessionLocal()
    try:
        logs = (
            db.query(models.RegularWorkLog)
            .filter(models.RegularWorkLog.regular_work_id == regular_work_id)
            .order_by(models.RegularWorkLog.created_at.desc())
            .limit(limit)
            .all()
        )
        if not logs:
            return "No logs found."
        return json.dumps([{
            "id": l.id, "status": l.status,
            "output": (l.output or "")[:500],
            "created_at": l.created_at.isoformat()
        } for l in logs], ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()
