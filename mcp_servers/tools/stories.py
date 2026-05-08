"""MCP tools for managing Stories (milestones / features within an Epic)."""
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
async def create_story(
    epic_id: str, user_id: str, title: str,
    description: Optional[str] = None,
    priority: Optional[str] = "medium"
) -> str:
    """
    Creates a Story (milestone/feature) within an Epic.
    - priority: high / medium / low
    """
    db = SessionLocal()
    try:
        err = require_approved(user_id, db)
        if err:
            return err
        story = models.Story(
            id=str(uuid.uuid4()),
            epic_id=epic_id,
            user_id=user_id,
            title=title,
            description=description,
            priority=priority or "medium",
            status="open",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(story)
        db.commit()
        db.refresh(story)
        return f"Story '{title}' created (ID: {story.id}) in Epic {epic_id}."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_story(
    story_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None
) -> str:
    """
    Updates a Story.
    - status: open / in_progress / done
    - priority: high / medium / low
    """
    db = SessionLocal()
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            return f"Story {story_id} not found."
        if title is not None: story.title = title
        if description is not None: story.description = description
        if status is not None: story.status = status
        if priority is not None: story.priority = priority
        story.updated_at = datetime.utcnow()
        db.commit()
        return f"Story {story_id} updated."
    except Exception as e:
        db.rollback()
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_stories(epic_id: str) -> str:
    """Lists all Stories within an Epic, ordered by priority and creation time."""
    db = SessionLocal()
    try:
        stories = db.query(models.Story).filter(models.Story.epic_id == epic_id).order_by(models.Story.created_at.asc()).all()
        if not stories:
            return f"No stories found for Epic {epic_id}."
        return json.dumps([{
            "id": s.id, "title": s.title, "status": s.status,
            "priority": s.priority, "description": s.description
        } for s in stories], ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()
