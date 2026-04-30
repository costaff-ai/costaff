"""MCP tools for ProjectTask comments (permanent task history)."""
import json
import uuid
from datetime import datetime

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp
from mcp_servers.tools._shared import require_approved


@mcp.tool()
async def add_task_comment(
    task_id: str, user_id: str, author: str,
    content: str, comment_type: str = "note"
) -> str:
    """
    Adds a comment to a ProjectTask. Comments are permanent and form the task history.
    - author: 'user' or the agent name (e.g. 'coding_agent')
    - comment_type: result / decision / issue / note
    """
    db = SessionLocal()
    try:
        err = require_approved(user_id, db)
        if err:
            return err
        task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()
        if not task:
            return f"Task {task_id} not found."
        comment = models.TaskComment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            user_id=user_id,
            author=author,
            content=content,
            type=comment_type,
            created_at=datetime.utcnow()
        )
        db.add(comment)
        db.commit()
        return f"Comment added to task {task_id}."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_task_comments(task_id: str) -> str:
    """Returns all comments on a ProjectTask, ordered chronologically."""
    db = SessionLocal()
    try:
        comments = db.query(models.TaskComment).filter(
            models.TaskComment.task_id == task_id
        ).order_by(models.TaskComment.created_at.asc()).all()
        if not comments:
            return f"No comments on task {task_id}."
        return json.dumps([{
            "id": c.id, "author": c.author, "type": c.type,
            "content": c.content, "created_at": c.created_at.isoformat()
        } for c in comments], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()
