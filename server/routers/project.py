"""Project Management endpoints — Epic / Story / ProjectTask hierarchy.

The dashboard's "Projects" view manages a 3-level hierarchy:
  Epic    — top-level project / long-term goal
  Story   — milestone or feature within an Epic (1 epic : many stories)
  Task    — atomic unit of work; lives directly under an Epic OR under a
            Story (1 story : many tasks). Tasks are what agents execute.

Cascade delete is implemented manually via raw SQL because the schema
predates SQLAlchemy `ON DELETE CASCADE` configuration.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from services.auth import AuthManager
from services.database import DatabaseManager

logger = logging.getLogger(__name__)
from server.schemas import (
    EpicCreateRequest, EpicUpdateRequest,
    StoryCreateRequest,
    ProjectTaskCreateRequest, ProjectTaskUpdateRequest,
)
from utils.helpers import _serialize_row

router = APIRouter()


# ---------------------------------------------------------------------------
# Epics
# ---------------------------------------------------------------------------

@router.get("/api/epics")
def list_epics(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            epics = conn.execute(text(
                "SELECT id, user_id, title, description, status, created_at, updated_at "
                "FROM epics ORDER BY created_at DESC"
            ))
            result = []
            for epic in epics:
                d = _serialize_row(dict(epic._mapping))
                # Attach task counts
                counts = conn.execute(text(
                    "SELECT status, COUNT(*) as cnt FROM project_tasks WHERE epic_id = :eid GROUP BY status"
                ), {"eid": d["id"]}).fetchall()
                d["task_counts"] = {r[0]: r[1] for r in counts}
                d["story_count"] = conn.execute(text(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = :eid"
                ), {"eid": d["id"]}).scalar() or 0
                result.append(d)
            return result
    except Exception:
        logger.exception("project router list-handler failed")
        return []


@router.post("/api/epics")
def create_epic_api(req: EpicCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        eid = str(uuid.uuid4())
        now = datetime.utcnow()
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO epics (id, user_id, title, description, status, created_at, updated_at) "
                "VALUES (:id, :user_id, :title, :description, :status, :now, :now)"
            ), {"id": eid, "user_id": req.user_id or "dashboard-user", "title": req.title,
                "description": req.description, "status": "active", "now": now})
            conn.commit()
        return {"status": "success", "id": eid}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/epics/{epic_id}")
def update_epic_api(epic_id: str, req: EpicUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        updates = req.dict(exclude_unset=True)
        if not updates:
            return {"status": "no changes"}
        updates["id"] = epic_id
        updates["now"] = datetime.utcnow()
        allowed = {"title", "description", "status"}
        set_clauses = [f"{k} = :{k}" for k in updates if k in allowed]
        set_clauses.append("updated_at = :now")
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE epics SET {', '.join(set_clauses)} WHERE id = :id"), updates)
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/epics/{epic_id}")
def delete_epic_api(epic_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM task_comments WHERE task_id IN (SELECT id FROM project_tasks WHERE epic_id = :eid)"), {"eid": epic_id})
            conn.execute(text("DELETE FROM project_tasks WHERE epic_id = :eid"), {"eid": epic_id})
            conn.execute(text("DELETE FROM stories WHERE epic_id = :eid"), {"eid": epic_id})
            conn.execute(text("DELETE FROM epics WHERE id = :id"), {"id": epic_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Stories (nested under Epics)
# ---------------------------------------------------------------------------

@router.get("/api/epics/{epic_id}/stories")
def get_stories_api(epic_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            stories = conn.execute(text(
                "SELECT id, title, description, status, priority, created_at FROM stories "
                "WHERE epic_id = :eid ORDER BY created_at ASC"
            ), {"eid": epic_id})
            result = []
            for s in stories:
                d = _serialize_row(dict(s._mapping))
                task_rows = conn.execute(text(
                    "SELECT id, title, spec, status, assigned_agent, priority FROM project_tasks "
                    "WHERE story_id = :sid ORDER BY queue_order ASC NULLS LAST, created_at ASC"
                ), {"sid": d["id"]}).fetchall()
                d["tasks"] = [dict(t._mapping) for t in task_rows]
                result.append(d)
            return result
    except Exception:
        logger.exception("project router list-handler failed")
        return []


@router.post("/api/epics/{epic_id}/stories")
def create_story_api(epic_id: str, req: StoryCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        sid = str(uuid.uuid4())
        now = datetime.utcnow()
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO stories (id, epic_id, user_id, title, description, status, priority, created_at, updated_at) "
                "VALUES (:id, :epic_id, :user_id, :title, :description, :status, :priority, :now, :now)"
            ), {"id": sid, "epic_id": epic_id, "user_id": req.user_id or "dashboard-user",
                "title": req.title, "description": req.description,
                "status": "open", "priority": req.priority or "medium", "now": now})
            conn.commit()
        return {"status": "success", "id": sid}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/epics/{epic_id}/stories/{story_id}")
def delete_story_api(epic_id: str, story_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM task_comments WHERE task_id IN (SELECT id FROM project_tasks WHERE story_id = :sid)"), {"sid": story_id})
            conn.execute(text("DELETE FROM project_tasks WHERE story_id = :sid"), {"sid": story_id})
            conn.execute(text("DELETE FROM stories WHERE id = :id AND epic_id = :eid"), {"id": story_id, "eid": epic_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Project Tasks (atomic unit; lives under Epic, optionally under Story)
# ---------------------------------------------------------------------------

@router.get("/api/project-tasks")
def list_project_tasks(epic_id: Optional[str] = None, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            q = "SELECT id, epic_id, story_id, title, spec, status, assigned_agent, priority, queue_order, created_at, updated_at FROM project_tasks"
            params = {}
            if epic_id:
                q += " WHERE epic_id = :eid"
                params["eid"] = epic_id
            q += " ORDER BY queue_order ASC NULLS LAST, created_at DESC"
            res = conn.execute(text(q), params)
            return [_serialize_row(dict(r._mapping)) for r in res]
    except Exception:
        logger.exception("project router list-handler failed")
        return []


@router.post("/api/project-tasks")
def create_project_task_api(req: ProjectTaskCreateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        tid = str(uuid.uuid4())
        now = datetime.utcnow()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO project_tasks (id, epic_id, story_id, user_id, session_id, title, spec,
                    type, assigned_agent, status, priority, created_at, updated_at)
                VALUES (:id, :epic_id, :story_id, :user_id, :session_id, :title, :spec,
                    :type, :assigned_agent, :status, :priority, :now, :now)
            """), {
                "id": tid, "epic_id": req.epic_id, "story_id": req.story_id,
                "user_id": req.user_id or "dashboard-user", "session_id": "dashboard-manual",
                "title": req.title, "spec": req.spec, "type": "immediate",
                "assigned_agent": req.assigned_agent, "status": "backlog",
                "priority": req.priority or "medium", "now": now
            })
            conn.commit()
        return {"status": "success", "id": tid}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/project-tasks/{task_id}")
def update_project_task_api(task_id: str, req: ProjectTaskUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        updates = req.dict(exclude_unset=True)
        if not updates:
            return {"status": "no changes"}
        updates["id"] = task_id
        updates["now"] = datetime.utcnow()
        allowed = {"title", "spec", "status", "priority", "assigned_agent"}
        set_clauses = [f"{k} = :{k}" for k in updates if k in allowed]
        set_clauses.append("updated_at = :now")
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE project_tasks SET {', '.join(set_clauses)} WHERE id = :id"), updates)
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/project-tasks/{task_id}")
def delete_project_task_api(task_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM task_comments WHERE task_id = :id"), {"id": task_id})
            conn.execute(text("DELETE FROM project_tasks WHERE id = :id"), {"id": task_id})
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.exception("project router handler failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/project-tasks/{task_id}/comments")
def get_task_comments(task_id: str, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(
                "SELECT id, author, content, type, created_at FROM task_comments "
                "WHERE task_id = :id ORDER BY created_at ASC"
            ), {"id": task_id})
            return [_serialize_row(dict(r._mapping)) for r in res]
    except Exception:
        logger.exception("project router list-handler failed")
        return []
