import asyncio
import uuid
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger

from core import models
from core.database import SessionLocal
from mcp_servers.setup import logger, scheduler, scheduled_job_ids, tz
from mcp_servers.executors.reminder import execute_reminder
from mcp_servers.executors.regular_work import execute_regular_work
from mcp_servers.executors.project_task import execute_project_task

# Window after which a 'doing' task with no progress is assumed orphaned.
# An asyncio worker that's actually alive will update `updated_at` (via status
# changes, comments, or callbacks) well within this window, so anything older
# is almost certainly a leftover from a container restart.
ORPHAN_THRESHOLD_MINUTES = 30


async def sync_database_tasks():
    """Periodically sync DB for active Reminders and RegularWorks into the scheduler."""
    while True:
        try:
            db = SessionLocal()
            active_job_ids = set()

            # Sync Reminders (one-time, pending)
            reminders = db.query(models.Reminder).filter(models.Reminder.status == "pending").all()
            for r in reminders:
                if not r.run_at:
                    continue
                job_id = f"reminder_{r.id}"
                active_job_ids.add(job_id)
                if job_id not in scheduled_job_ids:
                    from apscheduler.triggers.date import DateTrigger
                    try:
                        run_time = tz.localize(r.run_at) if r.run_at.tzinfo is None else r.run_at
                        scheduler.add_job(
                            execute_reminder, DateTrigger(run_date=run_time),
                            args=[r.id], id=job_id, replace_existing=True
                        )
                        scheduled_job_ids.add(job_id)
                        logger.info(f"Reminder {r.id} scheduled at {r.run_at}")
                    except Exception:
                        logger.exception("Failed to schedule reminder %s", r.id)

            # Sync RegularWorks (cron-based)
            works = db.query(models.RegularWork).filter(models.RegularWork.status == "active").all()
            for w in works:
                job_id = f"rwork_{w.id}"
                active_job_ids.add(job_id)
                if job_id not in scheduled_job_ids:
                    try:
                        scheduler.add_job(
                            execute_regular_work, CronTrigger.from_crontab(w.cron, timezone=tz),
                            args=[w.id], id=job_id, replace_existing=True
                        )
                        scheduled_job_ids.add(job_id)
                        logger.info(f"RegularWork {w.id} scheduled: {w.cron}")
                    except Exception:
                        logger.exception("Failed to schedule regular_work %s", w.id)

            # Sync scheduled ProjectTasks (cron-based)
            scheduled_tasks = db.query(models.ProjectTask).filter(
                models.ProjectTask.cron.isnot(None),
                models.ProjectTask.type == "scheduled"
            ).all()
            for t in scheduled_tasks:
                job_id = f"ptask_{t.id}"
                active_job_ids.add(job_id)
                if job_id not in scheduled_job_ids:
                    try:
                        scheduler.add_job(
                            execute_project_task, CronTrigger.from_crontab(t.cron, timezone=tz),
                            args=[t.id], id=job_id, replace_existing=True
                        )
                        scheduled_job_ids.add(job_id)
                        logger.info(f"ProjectTask {t.id} scheduled: {t.cron}")
                    except Exception:
                        logger.exception("Failed to schedule project_task %s", t.id)

            # Remove stale jobs
            current_ids = {job.id for job in scheduler.get_jobs()}
            for job_id in current_ids:
                if job_id.startswith(("reminder_", "rwork_", "ptask_")) and job_id not in active_job_ids:
                    try:
                        scheduler.remove_job(job_id)
                        scheduled_job_ids.discard(job_id)
                        logger.info(f"Removed stale job {job_id}")
                    except Exception:
                        logger.exception("Failed to remove job %s", job_id)

            db.close()
        except Exception:
            logger.exception("sync_database_tasks error")
        await asyncio.sleep(30)


async def poll_queued_tasks():
    """Poll for ProjectTasks with status='queued' that have no active predecessor."""
    while True:
        try:
            db = SessionLocal()
            queued = db.query(models.ProjectTask).filter(
                models.ProjectTask.status == "queued",
                models.ProjectTask.type == "immediate"
            ).order_by(
                models.ProjectTask.queue_order.asc().nullslast(),
                models.ProjectTask.created_at.asc()
            ).all()

            # Group by agent — only start one task per agent at a time
            agents_busy = set()
            doing = db.query(models.ProjectTask).filter(models.ProjectTask.status == "doing").all()
            for t in doing:
                if t.assigned_agent:
                    agents_busy.add(t.assigned_agent)

            for task in queued:
                agent = task.assigned_agent or "costaff_agent"
                if agent not in agents_busy:
                    agents_busy.add(agent)
                    asyncio.create_task(execute_project_task(task.id))

            db.close()
        except Exception:
            logger.exception("poll_queued_tasks error")
        await asyncio.sleep(5)


_DEFAULT_REGULAR_WORKS = [
    {
        "title": "Nightly Diary",
        "spec": (
            "Write today's daily diary for costaff_agent based on ADK event records.\n"
            "Call read_today_events(user_id) to get a summary of today's conversations,\n"
            "then call write_diary(user_id, agent_name='costaff_agent', date=<today>, done=<completed items>, next=<plan for tomorrow>, blocker=<blockers>).\n"
            "If there are no events, set done to 'No conversation records today' and blocker to null."
        ),
        "cron": "0 23 * * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
        "silent": True,
    },
    {
        "title": "Morning Team Summary",
        "spec": (
            "Call get_recent_diaries(user_id, days=1) to fetch yesterday's diaries for all agents,\n"
            "format the output as '📋 Yesterday's Team Work Summary' and deliver via send_message_now.\n"
            "Format: one section per agent, including ✅ completed items, ⚠️ blockers (if any), → today's plan.\n"
            "If there are no diaries, state 'No work records from yesterday'."
        ),
        "cron": "0 8 * * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
    {
        "title": "Weekly Work Summary",
        "spec": (
            "Call get_recent_diaries(user_id, days=7) to fetch this week's diaries,\n"
            "compile a weekly report and deliver via send_message_now.\n"
            "Include: items completed this week, main blockers, plan for next week.\n"
            "Use Telegram HTML formatting with the title '📊 Weekly Work Summary'."
        ),
        "cron": "0 22 * * 0",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
    {
        "title": "Monthly Work Review",
        "spec": (
            "Call get_recent_diaries(user_id, days=31) to fetch this month's diaries,\n"
            "and get_epics(user_id, status='active') to review project progress,\n"
            "compile a monthly report and deliver via send_message_now.\n"
            "Use Telegram HTML formatting with the title '🗓 Monthly Work Review'."
        ),
        "cron": "0 21 28 * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
]


def recover_orphaned_tasks() -> int:
    """Mark ProjectTasks stuck in 'doing' as 'failed' on MCP startup.

    When the MCP container restarts mid-task, the asyncio worker running
    `execute_project_task` dies but the DB record stays in 'doing'. Without
    cleanup, the Manager sees the stale record and reports the task as
    in-progress for the rest of the conversation, blocking the user from
    re-queueing the same work.

    This runs once at startup, before the scheduler starts and before any
    polling. Tasks last updated more than ORPHAN_THRESHOLD_MINUTES ago are
    flipped to 'failed' with a TaskComment that explains the reason.

    Returns the number of tasks recovered. Logged once for ops visibility.
    """
    db = SessionLocal()
    recovered = 0
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=ORPHAN_THRESHOLD_MINUTES)
        stuck = db.query(models.ProjectTask).filter(
            models.ProjectTask.status == "doing",
            models.ProjectTask.updated_at < cutoff,
        ).all()

        for task in stuck:
            stuck_since = task.updated_at  # capture BEFORE we overwrite it
            task.status = "failed"
            task.updated_at = datetime.utcnow()
            db.add(models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task.id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=(
                    f"## Task orphaned\n"
                    f"This task was stuck in 'doing' status for over "
                    f"{ORPHAN_THRESHOLD_MINUTES} minutes without progress. "
                    f"The MCP container likely restarted while the task was "
                    f"running, killing the asyncio worker. The task has been "
                    f"marked failed; re-queue it if you still need the result."
                ),
                type="issue",
                created_at=datetime.utcnow(),
            ))
            recovered += 1
            logger.warning(
                f"recover_orphaned_tasks: task {task.id} ({task.title!r}) "
                f"marked failed — was 'doing' since {stuck_since}"
            )

        if recovered:
            db.commit()
            logger.info(f"recover_orphaned_tasks: recovered {recovered} orphaned tasks")
    except Exception:
        db.rollback()
        logger.exception("recover_orphaned_tasks: failed to scan/clean")
    finally:
        db.close()
    return recovered


def _ensure_default_regular_works(user_id: str = None):
    """Create the 4 default global RegularWork entries (user_id='*') if none exist yet.
    The user_id parameter is kept for backwards compatibility but ignored.
    """
    db = SessionLocal()
    try:
        existing_count = db.query(models.RegularWork).filter(
            models.RegularWork.user_id == "*",
            models.RegularWork.session_id == "system-default",
        ).count()
        if existing_count > 0:
            return
        for w in _DEFAULT_REGULAR_WORKS:
            db.add(models.RegularWork(
                id=str(uuid.uuid4()),
                user_id="*",
                session_id="system-default",
                title=w["title"],
                spec=w["spec"],
                cron=w["cron"],
                agent_id=w["agent_id"],
                channel=w["channel"],
                recipient=w["recipient"],
                silent=w.get("silent", False),
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ))
        db.commit()
        logger.info("Created default global Regular Works (user_id='*')")
    except Exception:
        db.rollback()
        logger.exception("Failed to create default global Regular Works")
    finally:
        db.close()
