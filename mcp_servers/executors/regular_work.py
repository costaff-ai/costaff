import os
import asyncio
import json
import uuid
from datetime import datetime

from core import models
from core.database import SessionLocal
from core.adk_client import run_adk_prompt
from core.license import LicenseManager
from mcp_servers.setup import logger
from core.notifiers.dispatcher import dispatch_notification


async def execute_regular_work(regular_work_id: str):
    """Execute a RegularWork item by calling the designated agent.
    If work.user_id == '*', the work is global and runs for every registered user.
    """
    db = SessionLocal()
    try:
        work = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not work or work.status != "active":
            return

        logger.info(f"Executing RegularWork {regular_work_id}: {work.title}")

        # Global work: fan out to every user
        if work.user_id == "*":
            users = db.query(models.UserContact).all()
            db.close()
            tasks = [_run_for_user(regular_work_id, work, u.user_id) for u in users]
            await asyncio.gather(*tasks, return_exceptions=True)
            return

        await _run_for_user(regular_work_id, work, work.user_id)

    finally:
        if not db.is_active:
            return
        db.close()


async def _run_for_user(regular_work_id: str, work, user_id: str):
    """Execute a single RegularWork for one specific user."""
    from mcp_servers.task_helpers import get_user_channel_info
    db = SessionLocal()
    try:
        # Re-fetch work inside this session to avoid detached-instance issues
        work = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not work:
            return

        # Resolve delivery targets: multi-channel JSON first, then the legacy
        # single pair, then the user's default channel as a last resort.
        targets = []
        raw_channels = getattr(work, "channels", None)
        if raw_channels:
            try:
                targets = [
                    (t.get("channel"), t.get("recipient"))
                    for t in json.loads(raw_channels)
                    if isinstance(t, dict) and t.get("channel")
                ]
            except (ValueError, TypeError):
                logger.warning(f"RegularWork {regular_work_id}: unparseable channels JSON, falling back")
        if not targets and work.channel:
            targets = [(work.channel, work.recipient)]
        if not targets:
            channel, recipient = get_user_channel_info(user_id, db)
            if channel:
                targets = [(channel, recipient)]

        app_name = os.getenv("ADK_APP_NAME", "costaff_agent")
        session_id = f"rwork_{regular_work_id}_{user_id[:8]}"
        spec = (
            f"(System Context: Your ADK session user_id is '{user_id}'. "
            "Use this EXACT value whenever a tool requires a user_id parameter — "
            "do not invent placeholder values like 'abcdef1234567890'.)\n\n"
            "(AUTOMATED EXECUTION — NObody is watching this session to approve "
            "anything. This is ONE scheduled run of a task whose schedule ALREADY "
            "EXISTS; you are NOT being asked to set up or modify a schedule. You MUST "
            "carry out the steps below right now and return the finished result. Do "
            "NOT emit a plan / '執行計劃', do NOT ask the user to reply 'OK' or for any "
            "confirmation, and do NOT call create_regular_work / create_reminder or "
            "otherwise (re)register any scheduled job. Treat the text below as work to "
            "DO now, not as a request to schedule.)\n\n"
            + work.spec
        )
        deliverable = [(c, r) for c, r in targets if c and r]
        if deliverable:
            names = ", ".join(sorted({c for c, _ in deliverable}))
            spec += f"\n\n(System Note: This is a scheduled regular work. Deliver your output to the user via {names}. Do NOT call send_message_now for this recipient.)"

        try:
            result_text = await run_adk_prompt(app_name, user_id, session_id, spec)

            work.last_run = datetime.utcnow()
            work.updated_at = datetime.utcnow()

            new_log = models.RegularWorkLog(
                id=str(uuid.uuid4()),
                regular_work_id=regular_work_id,
                user_id=user_id,
                status="success",
                output=result_text,
                created_at=datetime.utcnow()
            )
            db.add(new_log)
            db.commit()

            if not work.silent:
                for ch, rec in deliverable:
                    try:
                        await dispatch_notification(ch, rec, result_text, session_id)
                    except Exception:
                        logger.exception(
                            f"RegularWork {regular_work_id}: delivery to {ch}/{rec} failed"
                        )

        except Exception as e:
            logger.error(f"RegularWork execution failed {regular_work_id} for user {user_id}: {e}")
            new_log = models.RegularWorkLog(
                id=str(uuid.uuid4()),
                regular_work_id=regular_work_id,
                user_id=user_id,
                status="failed",
                output=str(e),
                created_at=datetime.utcnow()
            )
            db.add(new_log)
            db.commit()

    finally:
        db.close()
