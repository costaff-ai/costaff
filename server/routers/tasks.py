import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text

from managers.auth import AuthManager
from managers.database import DatabaseManager
from server.schemas import (
    RegularWorkCreateRequest,
    RegularWorkUpdateRequest,
    EpicCreateRequest,
    EpicUpdateRequest,
    StoryCreateRequest,
    ProjectTaskCreateRequest,
    ProjectTaskUpdateRequest,
)
from managers.audit import audit
from utils.helpers import _serialize_row, _validate_cron

router = APIRouter()


# ---------------------------------------------------------------------------
# Regular Works API
# ---------------------------------------------------------------------------

@router.get("/api/regular-works")
def list_regular_works(auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(
                "SELECT id, user_id, title, spec, cron, agent_id, channel, recipient, status, last_run, next_run, created_at, updated_at "
                "FROM regular_works ORDER BY created_at ASC"
            ))
            return [_serialize_row(dict(r._mapping)) for r in res]
    except Exception:
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
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO regular_works (id, user_id, session_id, title, spec, cron, agent_id, channel, recipient, status, created_at, updated_at)
                VALUES (:id, :user_id, :session_id, :title, :spec, :cron, :agent_id, :channel, :recipient, :status, :now, :now)
            """), {
                "id": wid, "user_id": req.user_id or "dashboard-user",
                "session_id": "dashboard-manual", "title": req.title,
                "spec": req.spec, "cron": req.cron, "agent_id": req.agent_id or "costaff_agent",
                "channel": req.channel, "recipient": req.recipient,
                "status": "active", "now": now
            })
            conn.commit()
        audit("work.create", id=wid, title=req.title, cron=req.cron)
        return {"status": "success", "id": wid}
    except Exception as e:
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
        updates["id"] = work_id
        updates["now"] = datetime.utcnow()
        allowed = {"title", "spec", "cron", "agent_id", "channel", "recipient", "status"}
        set_clauses = [f"{k} = :{k}" for k in updates if k in allowed]
        set_clauses.append("updated_at = :now")
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE regular_works SET {', '.join(set_clauses)} WHERE id = :id"), updates)
            conn.commit()
        audit("work.update", id=work_id, changes={k: v for k, v in updates.items() if k not in ("id", "now")})
        return {"status": "success"}
    except Exception as e:
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
        return []


# ---------------------------------------------------------------------------
# Projects API — Epics / Stories / ProjectTasks
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        return []
