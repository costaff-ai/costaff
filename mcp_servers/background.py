import asyncio
import uuid
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger

from core import models
from core.database import SessionLocal
from mcp_servers.setup import logger, scheduler, scheduled_job_ids, tz
from mcp_servers.executors.reminder import execute_reminder
from mcp_servers.executors.regular_work import execute_regular_work
from mcp_servers.executors.project_task import (
    RUNNING_TASKS,
    execute_project_task,
    fail_task_and_notify,
)
from mcp_servers.task_helpers import normalize_agent_name

# Grace age for the PERIODIC orphan sweep. Live executors are excluded via
# RUNNING_TASKS, so this only shields 'doing' rows written by someone other
# than an executor (e.g. the Manager moving a Kanban card via
# update_task_status) from being reaped the moment they appear.
ORPHAN_THRESHOLD_MINUTES = 30

# How often the periodic sweep re-scans for orphans.
ORPHAN_SWEEP_INTERVAL_SECONDS = 300


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

            # Group by agent — only start one task per agent at a time.
            # Normalize names so "coding"/"coding_agent" count as one agent
            # (a raw compare would let both run → the anyio race).
            agents_busy = set()
            doing = db.query(models.ProjectTask).filter(models.ProjectTask.status == "doing").all()
            for t in doing:
                if t.assigned_agent:
                    agents_busy.add(normalize_agent_name(t.assigned_agent))

            for task in queued:
                agent = normalize_agent_name(task.assigned_agent or "costaff_agent")
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


async def recover_orphaned_tasks(max_age_minutes: int = ORPHAN_THRESHOLD_MINUTES) -> int:
    """Fail 'doing' ProjectTasks that no executor in this process owns.

    Every executor runs inside THIS MCP process and registers itself in
    RUNNING_TASKS, so a 'doing' row outside that set is verifiably
    orphaned — a container restart killed its worker, or a fire-and-forget
    asyncio task was lost mid-life.

    Called two ways:
    - startup (max_age_minutes=0): RUNNING_TASKS is empty after a restart,
      so EVERY 'doing' row is reaped immediately. The old 30-minute age
      gate left a window — restart within 30 minutes of a task starting
      and it stayed 'doing' forever, blocking the agent's whole queue.
    - periodic sweep (default age): catches workers lost while the process
      keeps running. The age gate only shields non-executor writers (e.g.
      Manager moving a Kanban card to 'doing' by hand).

    Each reaped task goes through fail_task_and_notify: issue comment,
    progress-panel finalize, user notification, and queue advance — so the
    agent's queue unblocks and dependents cascade instead of stranding.

    Returns the number of tasks recovered. Logged for ops visibility.
    """
    db = SessionLocal()
    recovered = 0
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        stuck = db.query(models.ProjectTask).filter(
            models.ProjectTask.status == "doing",
            models.ProjectTask.updated_at < cutoff,
        ).all()

        for task in stuck:
            if task.id in RUNNING_TASKS:
                continue  # a live executor in this process owns it
            stuck_since = task.updated_at  # capture BEFORE we overwrite it
            try:
                await fail_task_and_notify(
                    db, task,
                    "This task was orphaned — stuck in 'doing' with no live "
                    "worker (the MCP container likely restarted while it was "
                    "running). It has been marked failed; re-queue it if "
                    "you still need the result.",
                )
            except Exception:
                db.rollback()
                logger.exception(
                    "recover_orphaned_tasks: failed to reap task %s", task.id
                )
                continue
            recovered += 1
            logger.warning(
                f"recover_orphaned_tasks: task {task.id} ({task.title!r}) "
                f"marked failed — was 'doing' since {stuck_since}"
            )

        if recovered:
            logger.info(f"recover_orphaned_tasks: recovered {recovered} orphaned tasks")
    except Exception:
        db.rollback()
        logger.exception("recover_orphaned_tasks: failed to scan/clean")
    finally:
        db.close()
    return recovered


# Exponential backoff for outbox retries: attempt N waits 2^N minutes,
# capped, so a flapping channel isn't hammered. 8 attempts spans ~4 hours.
_OUTBOX_POLL_SECONDS = 30
_OUTBOX_BACKOFF_CAP_MINUTES = 60


async def process_outbox_once() -> int:
    """Retry due notification_outbox rows. Returns how many were sent.

    Rows whose next_attempt_at has passed are re-sent via the dispatcher
    (enqueue_on_failure=False so a repeat failure updates THIS row instead
    of creating a new one). Success → status='sent'. Exhausting
    max_attempts → status='dead' for ops to inspect.
    """
    from core.notifiers.dispatcher import dispatch_notification

    db = SessionLocal()
    sent = 0
    try:
        now = datetime.utcnow()
        due = db.query(models.NotificationOutbox).filter(
            models.NotificationOutbox.status == "pending",
            models.NotificationOutbox.next_attempt_at <= now,
        ).order_by(models.NotificationOutbox.next_attempt_at.asc()).limit(50).all()

        for row in due:
            ok = await dispatch_notification(
                row.channel, row.recipient, row.message,
                session_id=row.session_id, enqueue_on_failure=False,
            )
            row.attempts += 1
            row.updated_at = datetime.utcnow()
            if ok:
                row.status = "sent"
                sent += 1
            elif row.attempts >= row.max_attempts:
                row.status = "dead"
                logger.error(
                    "[outbox] notification %s dead after %d attempts "
                    "(channel=%s)", row.id, row.attempts, row.channel,
                )
            else:
                backoff = min(2 ** row.attempts, _OUTBOX_BACKOFF_CAP_MINUTES)
                row.next_attempt_at = datetime.utcnow() + timedelta(minutes=backoff)
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("[outbox] process_outbox_once error")
    finally:
        db.close()
    return sent


async def outbox_retry_loop():
    """Drain the notification outbox on a fixed poll; per-row backoff lives
    in the rows' next_attempt_at, so this loop itself stays simple."""
    while True:
        await asyncio.sleep(_OUTBOX_POLL_SECONDS)
        try:
            await process_outbox_once()
        except Exception:
            logger.exception("outbox_retry_loop error")


async def orphan_sweep_loop():
    """Periodic safety net behind the startup recovery.

    The startup pass only helps when the process restarts; a worker lost
    mid-life (fire-and-forget task garbage-collected or cancelled) leaves
    its row 'doing' with the process still up. This loop re-runs the same
    sweep — RUNNING_TASKS keeps genuinely live tasks safe no matter how
    long they run.
    """
    while True:
        await asyncio.sleep(ORPHAN_SWEEP_INTERVAL_SECONDS)
        try:
            await recover_orphaned_tasks(ORPHAN_THRESHOLD_MINUTES)
        except Exception:
            logger.exception("orphan_sweep_loop error")


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
