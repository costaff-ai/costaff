import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp
from mcp_servers.executors.project_task import execute_project_task

logger = logging.getLogger("costaff-agent-engine")


def _require_approved(user_id: str, db) -> "str | None":
    """Returns denial message if user is unapproved; None grants access.
    Users with no identity_maps record (admin/system) are always granted access.
    """
    mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == user_id).first()
    if mapping is not None and not mapping.is_approved:
        return "Access denied: your account has not been approved. Please contact an administrator."
    return None


@mcp.tool()
async def create_epic(user_id: str, title: str, description: Optional[str] = None) -> str:
    """
    Creates a new Epic (top-level project).
    Examples: 'Expense tracker', 'costaff development', 'Health management plan'
    """
    db = SessionLocal()
    try:
        err = _require_approved(user_id, db)
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
        err = _require_approved(user_id, db)
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
        return f"Error: {str(e)}"
    finally:
        db.close()


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
        err = _require_approved(user_id, db)
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
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def create_project_task(
    epic_id: str, user_id: str, title: str,
    spec: Optional[str] = None,
    story_id: Optional[str] = None,
    assigned_agent: Optional[str] = None,
    priority: Optional[str] = "medium",
    depends_on: Optional[str] = None,
    session_id: Optional[str] = None,
    channel: Optional[str] = None,
    recipient: Optional[str] = None,
    cron: Optional[str] = None
) -> str:
    """
    Creates a ProjectTask within an Epic (and optionally a Story).

    IMPORTANT — Before calling this tool, YOU (the agent) must write the spec yourself.
    The spec is the most critical field: it is the exact prompt the executing agent will receive.
    A vague spec produces vague results. Write it clearly before passing it in.

    ## spec format (5W1H per use case)

    Write the spec in English using this structure (the executing agent
    will translate its final user-facing output to the user's preferred language):

    # {task title}

    ## Background
    {one sentence: which epic/story this belongs to and why this task exists}

    ## Use Cases

    ### Case 1: {case name}
    - **When**: {trigger / condition}
    - **What**: {the behaviour or output}
    - **Where**: {location, component, URL, file — if applicable}
    - **Why**: {purpose — if not obvious}
    - **How**: {implementation approach — if applicable}

    ### Case 2: {case name}
    ...(repeat for each distinct use case or sub-feature)

    ## Acceptance Criteria
    - [ ] {concrete, testable criterion}
    - [ ] ...

    Rules:
    - Include only the W/H items that are meaningful for each case; skip the rest.
    - Be specific: name actual components, endpoints, fields, or file paths where known.
    - Each use case should be independently understandable by the executing agent.
    - CRITICAL — output file paths: if the task produces output files, the acceptance criteria
      MUST include the full absolute path for each output file, using exactly this format:
        - [ ] File exists at /app/data/shared/<agent-name>/<filename>
      Never write just the filename alone (e.g. `report.pdf`) — always the full path.
      This is required for automated acceptance checking.

    Other fields:
    - assigned_agent: 'coding_agent' for code/files; 'costaff_agent' for planning/coordination.
    - depends_on: task_id that must be 'done' before this task starts.
    - cron: if set, task type becomes 'scheduled'.
    - priority: high / medium / low.

    The task starts with status='backlog'. Use update_task_queue to enqueue it.
    """
    logger.info(f"[create_project_task] epic={epic_id} agent={assigned_agent} title={title!r}")
    db = SessionLocal()
    try:
        err = _require_approved(user_id, db)
        if err:
            return err
        # Fallback spec if agent did not provide one
        if not spec:
            epic = db.query(models.Epic).filter(models.Epic.id == epic_id).first()
            story = None
            if story_id:
                story = db.query(models.Story).filter(models.Story.id == story_id).first()

            epic_title  = epic.title if epic else "(Unknown Project)"
            epic_desc   = epic.description if epic and epic.description else ""
            story_title = story.title if story else ""
            story_desc  = story.description if story and story.description else ""

            context_lines = []
            if epic_desc:  context_lines.append(epic_desc)
            if story_desc: context_lines.append(story_desc)
            context = "; ".join(context_lines) if context_lines else f"Achieve the goal of {epic_title}"

            spec = (
                f"# {title}\n\n"
                f"## Background\n"
                f"Parent Project: {epic_title}"
                + (f"  |  Story: {story_title}" if story_title else "")
                + f"\n{context}\n\n"
                f"## Use Cases\n\n"
                f"### Case 1: {title}\n"
                f"- **When**: when the task runs\n"
                f"- **What**: complete the development and implementation of \"{title}\"\n"
                f"- **Where**: {epic_title}" + (f" > {story_title}" if story_title else "") + "\n"
                f"- **How**: analyze requirements → plan approach → implement → verify → report summary\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] Feature works correctly\n"
                f"- [ ] Completion summary delivered\n"
            )

        task_type = "scheduled" if cron else "immediate"
        task = models.ProjectTask(
            id=str(uuid.uuid4()),
            epic_id=epic_id,
            story_id=story_id,
            user_id=user_id,
            session_id=session_id,
            title=title,
            spec=spec,
            type=task_type,
            assigned_agent=assigned_agent,
            priority=priority or "medium",
            depends_on=depends_on,
            cron=cron,
            channel=channel,
            recipient=recipient,
            status="backlog",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        result = f"Task '{title}' created (ID: {task.id}) in Epic {epic_id}."
        logger.info(f"[create_project_task] OK → {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"[create_project_task] Error: {e}")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_task_status(task_id: str, status: str) -> str:
    """
    Updates a ProjectTask's status.
    - status: backlog / queued / doing / done / failed
    Agents call this to move tasks across the Kanban board.
    """
    db = SessionLocal()
    try:
        task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()
        if not task:
            return f"Task {task_id} not found."
        task.status = status
        task.updated_at = datetime.utcnow()
        db.commit()
        # Event-driven: fire execution immediately when queued, don't wait for poll interval
        if status == "queued" and task.type == "immediate":
            asyncio.create_task(execute_project_task(task_id))
        return f"Task {task_id} status updated to '{status}'."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_task_queue(user_id: str, assigned_agent: str, task_ids_ordered: list) -> str:
    """
    Sets the queue order for an agent's tasks and marks them as queued for execution.
    costaff_agent calls this to prioritize which tasks run first.
    - task_ids_ordered: JSON array of task ID strings in desired execution order (first = highest priority)
      Example: ["uuid-1", "uuid-2", "uuid-3"]
    """
    logger.info(f"[update_task_queue] agent={assigned_agent!r} task_ids={task_ids_ordered!r}")
    db_check = SessionLocal()
    try:
        err = _require_approved(user_id, db_check)
        if err:
            return err
    finally:
        db_check.close()
    # Defensive: LLMs sometimes pass a JSON-encoded string instead of a list
    if isinstance(task_ids_ordered, str):
        try:
            task_ids_ordered = json.loads(task_ids_ordered)
        except Exception:
            return "Error: task_ids_ordered must be a JSON array of task ID strings."

    if not isinstance(task_ids_ordered, list):
        return "Error: task_ids_ordered must be a list."

    db = SessionLocal()
    try:
        updated_count = 0
        first_task_id = None

        # Normalize agent name (handle costaff-agent-coding vs coding_agent)
        norm_agent = assigned_agent.replace("-", "_")

        for idx, task_id in enumerate(task_ids_ordered):
            task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()

            if not task:
                logger.warning(f"[update_task_queue] task {task_id} not found in DB")
                continue

            task_norm = task.assigned_agent.replace("-", "_")
            if task_norm != norm_agent:
                logger.warning(f"[update_task_queue] agent mismatch: task has {task.assigned_agent!r}, expected {assigned_agent!r}")
                continue

            task.queue_order = idx + 1
            task.status = "queued"
            task.updated_at = datetime.utcnow()
            updated_count += 1
            if idx == 0:
                first_task_id = task_id

        db.commit()

        # Trigger immediate execution for the first task in queue
        if first_task_id:
            asyncio.create_task(execute_project_task(first_task_id))
            logger.info(f"[update_task_queue] triggered execute_project_task for {first_task_id}")

        result = f"Queue updated for agent '{assigned_agent}': {updated_count} tasks marked as queued. Execution triggered."
        logger.info(f"[update_task_queue] OK → {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"[update_task_queue] Error: {e}")
        return f"Internal Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_agent_queue(user_id: str, assigned_agent: str) -> str:
    """
    Returns the current task queue for a specific agent, ordered by queue_order.
    Shows backlog, queued, and doing tasks only.
    """
    db = SessionLocal()
    try:
        err = _require_approved(user_id, db)
        if err:
            return err
        tasks = (
            db.query(models.ProjectTask)
            .filter(
                models.ProjectTask.assigned_agent == assigned_agent,
                models.ProjectTask.status.in_(["backlog", "queued", "doing"])
            )
            .order_by(
                models.ProjectTask.queue_order.asc().nullslast(),
                models.ProjectTask.created_at.asc()
            )
            .all()
        )
        if not tasks:
            return f"No pending tasks for agent '{assigned_agent}'."
        return json.dumps([{
            "id": t.id, "title": t.title, "status": t.status,
            "priority": t.priority, "queue_order": t.queue_order,
            "epic_id": t.epic_id, "depends_on": t.depends_on
        } for t in tasks], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_next_task(user_id: str, assigned_agent: str) -> str:
    """
    Returns the next task to execute for an agent.
    Only returns tasks with status='queued' whose dependencies (if any) are done.
    """
    db = SessionLocal()
    try:
        err = _require_approved(user_id, db)
        if err:
            return err
        tasks = (
            db.query(models.ProjectTask)
            .filter(
                models.ProjectTask.assigned_agent == assigned_agent,
                models.ProjectTask.status == "queued"
            )
            .order_by(
                models.ProjectTask.queue_order.asc().nullslast(),
                models.ProjectTask.created_at.asc()
            )
            .all()
        )
        for task in tasks:
            if task.depends_on:
                dep = db.query(models.ProjectTask).filter(models.ProjectTask.id == task.depends_on).first()
                if dep and dep.status != "done":
                    continue
            return json.dumps({
                "id": task.id, "title": task.title, "spec": task.spec,
                "priority": task.priority, "epic_id": task.epic_id
            }, ensure_ascii=False, indent=2)
        return "No tasks ready to execute."
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()


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
        err = _require_approved(user_id, db)
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


@mcp.tool()
async def get_project_tasks(
    user_id: str,
    epic_id: Optional[str] = None,
    story_id: Optional[str] = None,
    assigned_agent: Optional[str] = None,
    status: Optional[str] = None
) -> str:
    """
    Lists ProjectTasks with optional filters.
    - epic_id: filter by Epic
    - story_id: filter by Story
    - assigned_agent: filter by agent
    - status: backlog / queued / doing / done / failed
    """
    db = SessionLocal()
    try:
        err = _require_approved(user_id, db)
        if err:
            return err
        q = db.query(models.ProjectTask)
        if epic_id: q = q.filter(models.ProjectTask.epic_id == epic_id)
        if story_id: q = q.filter(models.ProjectTask.story_id == story_id)
        if assigned_agent: q = q.filter(models.ProjectTask.assigned_agent == assigned_agent)
        if status: q = q.filter(models.ProjectTask.status == status)
        tasks = q.order_by(models.ProjectTask.queue_order.asc().nullslast(), models.ProjectTask.created_at.desc()).all()
        if not tasks:
            return "No tasks found."
        return json.dumps([{
            "id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
            "assigned_agent": t.assigned_agent, "queue_order": t.queue_order,
            "epic_id": t.epic_id, "story_id": t.story_id, "depends_on": t.depends_on
        } for t in tasks], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()
