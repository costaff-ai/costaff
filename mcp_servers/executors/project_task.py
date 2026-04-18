import os
import asyncio
import uuid
from datetime import datetime

from src.core import models
from src.core.database import SessionLocal
from src.core.adk_client import run_adk_prompt
from src.core.license import LicenseManager, ExecutionWarning
from mcp_servers.core import logger
from mcp_servers.utils import _send_notification, _get_user_channel_info, _build_task_spec


async def execute_project_task(task_id: str):
    """Execute a ProjectTask by calling costaff_agent with full project context."""
    db = SessionLocal()
    try:
        task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()
        if not task or task.status in ("doing",):
            return

        # Check dependency
        if task.depends_on:
            dep = db.query(models.ProjectTask).filter(models.ProjectTask.id == task.depends_on).first()
            if dep and dep.status not in ("done",):
                logger.info(f"ProjectTask {task_id} waiting on dependency {task.depends_on}")
                return

        logger.info(f"Executing ProjectTask {task_id}: {task.title}")

        # Resolve channel/recipient — auto-detect from IdentityMap if not set on task
        channel = task.channel
        recipient = task.recipient
        if not channel:
            channel, recipient = _get_user_channel_info(task.user_id, db)

        try:
            LicenseManager.check_execution_limit(task.user_id, db)
        except ExecutionWarning as w:
            if channel and recipient:
                asyncio.create_task(_send_notification(channel, recipient, f"⚠️ {str(w)}", None))
        except ValueError as e:
            task.status = "backlog"
            db.commit()
            if channel and recipient:
                asyncio.create_task(_send_notification(channel, recipient, f"🚫 {str(e)}", None))
            return

        task.status = "doing"
        task.updated_at = datetime.utcnow()
        db.commit()

        # Write start comment
        start_comment = models.TaskComment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            user_id=task.user_id,
            author=task.assigned_agent or "costaff_agent",
            content=(
                f"## 🚀 開始執行\n"
                f"- **任務**：{task.title}\n"
                f"- **指派 Agent**：{task.assigned_agent or 'costaff_agent'}\n"
                f"- **任務說明**：{(task.spec or '').strip()[:300] or '—'}"
            ),
            type="note",
            created_at=datetime.utcnow()
        )
        db.add(start_comment)
        db.commit()

        # Build context-enriched spec and use task-scoped session to prevent context bleed
        spec = _build_task_spec(task, db)
        task_session_id = f"task_{task_id}"
        app_name = os.getenv("ADK_APP_NAME", "costaff_agent")

        try:
            result_text = await run_adk_prompt(app_name, task.user_id, task_session_id, spec)

            task.status = "done"
            task.last_run = datetime.utcnow()
            task.updated_at = datetime.utcnow()

            comment = models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task_id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=result_text,
                type="result",
                created_at=datetime.utcnow()
            )
            db.add(comment)
            db.commit()

            if channel and recipient:
                await _send_notification(channel, recipient, result_text, task_session_id)

            # Advance queue and wake up dependents
            if task.assigned_agent:
                asyncio.create_task(_advance_agent_queue(task.assigned_agent, task.user_id, finished_task_id=task_id))

            except Exception as e:
            logger.error(f"ProjectTask execution failed {task_id}: {e}")
            task.status = "failed"
            task.updated_at = datetime.utcnow()
            import traceback
            comment = models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task_id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=(
                    f"## ❌ 錯誤發生\n"
                    f"- **錯誤類型**：{type(e).__name__}\n"
                    f"- **錯誤訊息**：{str(e)}\n"
                    f"- **發生位置**：Agent 執行階段（task_id={task_id}）\n"
                    f"- **詳細 Traceback**：\n```\n{traceback.format_exc()[-1000:]}\n```"
                ),
                type="issue",
                created_at=datetime.utcnow()
            )
            db.add(comment)
            db.commit()

            # Still advance the queue even on failure so remaining tasks are not blocked
            if task.assigned_agent:
                asyncio.create_task(_advance_agent_queue(task.assigned_agent, task.user_id, finished_task_id=task_id))


    finally:
        db.close()


async def _advance_agent_queue(agent_id: str, user_id: str, finished_task_id: str = None):
    """
    1. Pick up the next already-queued task for this specific agent.
    2. [NEW] Wake up any dependent tasks (from ANY agent) that were waiting for this finished task.
    """
    db = SessionLocal()
    try:
        # 1. Trigger dependent tasks across the whole project
        if finished_task_id:
            dependents = (
                db.query(models.ProjectTask)
                .filter(models.ProjectTask.depends_on == finished_task_id)
                .all()
            )
            for dep_task in dependents:
                if dep_task.status == "backlog":
                    logger.info(f"Dependency met! Queuing dependent task: {dep_task.id} (Agent: {dep_task.assigned_agent})")
                    dep_task.status = "queued"
                    dep_task.updated_at = datetime.utcnow()
                    db.commit() # Commit each change immediately to avoid race
                    asyncio.create_task(execute_project_task(dep_task.id))

        # 2. Advance the original agent's own queue (existing logic)
        next_task = (
            db.query(models.ProjectTask)
            .filter(
                models.ProjectTask.assigned_agent == agent_id,
                models.ProjectTask.user_id == user_id,
                models.ProjectTask.status == "queued"
            )
            .order_by(models.ProjectTask.queue_order.asc().nullslast(), models.ProjectTask.created_at.asc())
            .first()
        )
        if next_task:
            logger.info(f"Advancing queue: next task for {agent_id} is {next_task.id}")
            asyncio.create_task(execute_project_task(next_task.id))
    finally:
        db.close()
