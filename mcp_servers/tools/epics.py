"""MCP tools for managing Epics (top-level projects)."""
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp
from mcp_servers.tools._shared import require_approved

logger = logging.getLogger(__name__)


@mcp.tool()
async def create_epic(user_id: str, title: str, description: Optional[str] = None) -> str:
    """
    Creates a new Epic (top-level project).
    Examples: 'Expense tracker', 'costaff development', 'Health management plan'
    """
    db = SessionLocal()
    try:
        err = require_approved(user_id, db)
        if err:
            return err
        epic = models.Epic(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            description=description,
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(epic)
        db.commit()
        db.refresh(epic)
        return f"Epic '{title}' created (ID: {epic.id})."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_epic(
    epic_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None
) -> str:
    """
    Updates an Epic's title, description, or status.
    - status: active / completed / archived
    """
    db = SessionLocal()
    try:
        epic = db.query(models.Epic).filter(models.Epic.id == epic_id).first()
        if not epic:
            return f"Epic {epic_id} not found."
        if title is not None: epic.title = title
        if description is not None: epic.description = description
        if status is not None: epic.status = status
        epic.updated_at = datetime.utcnow()
        db.commit()
        return f"Epic {epic_id} updated."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_epics(user_id: str, status: Optional[str] = None) -> str:
    """
    Lists all team Epics. Requires an approved account.
    - status: optional filter — 'active', 'completed', 'archived'
    """
    db = SessionLocal()
    try:
        err = require_approved(user_id, db)
        if err:
            return err
        q = db.query(models.Epic)
        if status:
            q = q.filter(models.Epic.status == status)
        epics = q.order_by(models.Epic.created_at.desc()).all()
        if not epics:
            return "No epics found."
        return json.dumps([{
            "id": e.id, "title": e.title, "description": e.description,
            "status": e.status, "created_at": e.created_at.isoformat()
        } for e in epics], ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_epic_detail(epic_id: str) -> str:
    """
    Returns full detail of an Epic including all Stories and their Tasks.
    Use this to get a complete picture of a project's history and current state.
    """
    db = SessionLocal()
    try:
        epic = db.query(models.Epic).filter(models.Epic.id == epic_id).first()
        if not epic:
            return f"Epic {epic_id} not found."

        stories = db.query(models.Story).filter(models.Story.epic_id == epic_id).order_by(models.Story.created_at.asc()).all()
        story_data = []
        for s in stories:
            tasks = db.query(models.ProjectTask).filter(models.ProjectTask.story_id == s.id).order_by(models.ProjectTask.queue_order.asc().nullslast(), models.ProjectTask.created_at.asc()).all()
            story_data.append({
                "id": s.id, "title": s.title, "status": s.status, "priority": s.priority,
                "tasks": [{"id": t.id, "title": t.title, "status": t.status, "assigned_agent": t.assigned_agent} for t in tasks]
            })

        # Tasks directly under epic (no story)
        direct_tasks = db.query(models.ProjectTask).filter(
            models.ProjectTask.epic_id == epic_id,
            models.ProjectTask.story_id.is_(None)
        ).order_by(models.ProjectTask.queue_order.asc().nullslast(), models.ProjectTask.created_at.asc()).all()

        return json.dumps({
            "id": epic.id, "title": epic.title, "description": epic.description,
            "status": epic.status, "created_at": epic.created_at.isoformat(),
            "stories": story_data,
            "direct_tasks": [{"id": t.id, "title": t.title, "status": t.status, "assigned_agent": t.assigned_agent} for t in direct_tasks]
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()
