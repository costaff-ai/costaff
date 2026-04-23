import asyncio
import uuid
from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

from src.core import models
from src.core.database import SessionLocal
from mcp_servers.core import logger, scheduler, scheduled_job_ids, tz
from mcp_servers.executors.reminder import execute_reminder
from mcp_servers.executors.regular_work import execute_regular_work
from mcp_servers.executors.project_task import execute_project_task


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
                    except Exception as e:
                        logger.error(f"Failed to schedule reminder {r.id}: {e}")

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
                    except Exception as e:
                        logger.error(f"Failed to schedule regular_work {w.id}: {e}")

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
                    except Exception as e:
                        logger.error(f"Failed to schedule project_task {t.id}: {e}")

            # Remove stale jobs
            current_ids = {job.id for job in scheduler.get_jobs()}
            for job_id in current_ids:
                if job_id.startswith(("reminder_", "rwork_", "ptask_")) and job_id not in active_job_ids:
                    try:
                        scheduler.remove_job(job_id)
                        scheduled_job_ids.discard(job_id)
                        logger.info(f"Removed stale job {job_id}")
                    except Exception as e:
                        logger.warning(f"Failed to remove job {job_id}: {e}")

            db.close()
        except Exception as e:
            logger.error(f"sync_database_tasks error: {e}")
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
        except Exception as e:
            logger.error(f"poll_queued_tasks error: {e}")
        await asyncio.sleep(5)


_DEFAULT_REGULAR_WORKS = [
    {
        "title": "夜間日記撰寫",
        "spec": (
            "請根據今日 ADK events 紀錄，幫 costaff_agent 撰寫每日日記。\n"
            "呼叫 read_today_events(user_id) 取得今日對話摘要，\n"
            "再呼叫 write_diary(user_id, agent_name='costaff_agent', date=<today>, done=<完成事項>, next=<明日計畫>, blocker=<阻礙事項>)。\n"
            "若無任何事件，done 寫「今日無對話紀錄」，blocker 為 null。"
        ),
        "cron": "0 23 * * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
    {
        "title": "晨間團隊摘要報告",
        "spec": (
            "請呼叫 get_recent_diaries(user_id, days=1) 取得昨日所有 Agent 的日記，\n"
            "整理成「📋 昨日團隊工作摘要」格式並使用 send_message_now 發送給使用者。\n"
            "格式：每個 Agent 一段，包含 ✅ 完成項目、⚠️ 阻礙（若有）、→ 今日計畫。\n"
            "若無日記，說明「昨日無工作紀錄」。"
        ),
        "cron": "0 8 * * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
    {
        "title": "每週工作總結",
        "spec": (
            "請呼叫 get_recent_diaries(user_id, days=7) 取得本週所有日記，\n"
            "整理成週報並使用 send_message_now 發送給使用者。\n"
            "包含：本週完成事項、主要阻礙、下週計畫。\n"
            "格式請使用 Telegram HTML，標題為「📊 本週工作總結」。"
        ),
        "cron": "0 22 * * 0",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
    {
        "title": "每月工作回顧",
        "spec": (
            "請呼叫 get_recent_diaries(user_id, days=31) 取得本月所有日記，\n"
            "以及 get_epics(user_id, status='active') 了解專案進度，\n"
            "整理成月報並使用 send_message_now 發送給使用者。\n"
            "格式請使用 Telegram HTML，標題為「🗓 本月工作回顧」。"
        ),
        "cron": "0 21 28-31 * *",
        "agent_id": "costaff_agent",
        "channel": None,
        "recipient": None,
    },
]


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
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ))
        db.commit()
        logger.info("Created default global Regular Works (user_id='*')")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create default global Regular Works: {e}")
    finally:
        db.close()
