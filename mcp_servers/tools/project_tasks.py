"""MCP tools for managing ProjectTasks (Kanban-style work items).

Includes the queue / scheduling primitives that costaff_agent uses to
prioritize work across multiple specialist agents.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from mcp_servers.executors.project_task import execute_project_task
from mcp_servers.setup import mcp
from mcp_servers.tools._shared import require_approved

logger = logging.getLogger("costaff-agent-engine")


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

    ⚠ LEGACY — prefer `dispatch_task` for normal dispatch. This tool leaves the
    task in `backlog` status and REQUIRES a follow-up `update_task_queue` call
    in the same turn, otherwise the task is stranded and never executes.
    Only use this if you genuinely need a two-phase create (rare).

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
        err = require_approved(user_id, db)
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
        logger.exception("[create_project_task] failed")
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def dispatch_task(
    epic_id: str, user_id: str, title: str, assigned_agent: str,
    spec: Optional[str] = None,
    story_id: Optional[str] = None,
    priority: Optional[str] = "medium",
    depends_on: Optional[str] = None,
    session_id: Optional[str] = None,
    channel: Optional[str] = None,
    recipient: Optional[str] = None,
    cron: Optional[str] = None
) -> str:
    """
    Atomically creates a ProjectTask and immediately enqueues it for execution.

    THIS IS THE PREFERRED dispatch tool. Use this instead of the older two-step
    `create_project_task` + `update_task_queue` flow. A single atomic call means
    a task can never be stranded in `backlog` because the LLM forgot the second step.

    Parameters mirror `create_project_task`, with one difference:
      - `assigned_agent` is REQUIRED (you cannot dispatch to nobody).

    Behaviour:
      - Task is inserted with status='queued' and queue_order = (current max for
        this agent's open tasks) + 1, so it appends to the end of the agent's queue.
      - If type is 'immediate' (no `cron`), the executor is triggered right away.
      - If `cron` is set, the task is created as 'scheduled' and not run immediately.
      - **Auto-chain**: if `depends_on` is not provided AND there is an in-progress
        (queued / doing) task for the same `(user_id, session_id)`, this new task
        is auto-linked via `depends_on` and inserted as `backlog`. The executor
        will wake it via `_advance_agent_queue` after the upstream finishes.
        This prevents accidental parallel dispatch in a chain (Principle 3) —
        Manager can call `dispatch_task` twice back-to-back and the second call
        will queue cleanly behind the first instead of racing it.

    Spec format: see `create_project_task` — write the spec yourself before calling.

    Returns: success message with task_id.
    """
    logger.info(f"[dispatch_task] epic={epic_id} agent={assigned_agent} title={title!r}")
    if not assigned_agent:
        return "Error: assigned_agent is required for dispatch_task."

    db = SessionLocal()
    try:
        err = require_approved(user_id, db)
        if err:
            return err

        # Auto-chain: if this dispatch belongs to a user/session that already
        # has work in flight, link it as a dependent rather than letting it
        # race the upstream. The Manager LLM is supposed to enforce this via
        # Principle 3 ("one specialist at a time"), but does not always — and
        # the executor is the only layer that can structurally guarantee it.
        if not depends_on and session_id:
            in_progress = (
                db.query(models.ProjectTask)
                .filter(
                    models.ProjectTask.user_id == user_id,
                    models.ProjectTask.session_id == session_id,
                    models.ProjectTask.status.in_(["queued", "doing"]),
                )
                .order_by(models.ProjectTask.created_at.desc())
                .first()
            )
            if in_progress:
                depends_on = in_progress.id
                logger.info(
                    f"[dispatch_task] auto-linked depends_on={depends_on} "
                    f"(in-progress task {in_progress.title!r} for same session)"
                )

        # Fallback spec — same shape as create_project_task
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

        # Append to the end of this agent's open queue
        existing_max = (
            db.query(models.ProjectTask.queue_order)
            .filter(
                models.ProjectTask.assigned_agent == assigned_agent,
                models.ProjectTask.status.in_(["backlog", "queued", "doing"]),
            )
            .order_by(models.ProjectTask.queue_order.desc().nullslast())
            .limit(1)
            .scalar()
        )
        next_order = (existing_max or 0) + 1

        task_type = "scheduled" if cron else "immediate"
        # backlog when waiting on a dependency — _advance_agent_queue will
        # promote it to queued and trigger the executor once the upstream
        # task is done.
        if cron:
            initial_status = "scheduled"
        elif depends_on:
            initial_status = "backlog"
        else:
            initial_status = "queued"

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
            status=initial_status,
            queue_order=next_order,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Immediate, dependency-free tasks: hand to executor right now (do not
        # wait for poll loop). Scheduled (cron) and backlog (waiting on a
        # dependency) tasks are picked up later by APScheduler or by
        # `_advance_agent_queue` respectively.
        if task_type == "immediate" and initial_status == "queued":
            asyncio.create_task(execute_project_task(task.id))
            logger.info(f"[dispatch_task] triggered execute_project_task for {task.id}")

        result = (
            f"Task '{title}' dispatched (ID: {task.id}, agent: {assigned_agent}, "
            f"queue_order: {next_order}, status: {initial_status})."
        )
        logger.info(f"[dispatch_task] OK → {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.exception("[dispatch_task] failed")
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
        logger.exception("MCP tool failed")
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

    ⚠ LEGACY — for new dispatch use `dispatch_task` (atomic create+queue).
    This tool is still valid for RE-ORDERING an existing queue, but for first-time
    dispatch you should not be calling create_project_task → update_task_queue;
    use `dispatch_task` instead.
    """
    logger.info(f"[update_task_queue] agent={assigned_agent!r} task_ids={task_ids_ordered!r}")
    db_check = SessionLocal()
    try:
        err = require_approved(user_id, db_check)
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

        # Normalize agent name. The caller (manager LLM) may pass any of these:
        #   "coding", "coding_agent", "costaff-agent-coding", "business_analysis_agent"
        # and `task.assigned_agent` recorded in DB at create-time may use a
        # different form. Strip the "_agent" / "agent" suffix and convert
        # hyphens to underscores so all four spellings collapse to one bare key.
        def _norm(name: str) -> str:
            n = (name or "").replace("-", "_")
            if n.startswith("costaff_agent_"):
                n = n[len("costaff_agent_"):]
            if n.endswith("_agent"):
                n = n[:-len("_agent")]
            return n

        norm_agent = _norm(assigned_agent)

        for idx, task_id in enumerate(task_ids_ordered):
            task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()

            if not task:
                logger.warning(f"[update_task_queue] task {task_id} not found in DB")
                continue

            task_norm = _norm(task.assigned_agent)
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
        logger.exception("[update_task_queue] failed")
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
        err = require_approved(user_id, db)
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
        logger.exception("MCP tool failed")
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
        err = require_approved(user_id, db)
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
        logger.exception("MCP tool failed")
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
        err = require_approved(user_id, db)
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
        logger.exception("MCP tool failed")
        return f"Error: {str(e)}"
    finally:
        db.close()
