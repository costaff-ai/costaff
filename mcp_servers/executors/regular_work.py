import os
import asyncio
import uuid
from datetime import datetime

from core import models
from core.database import SessionLocal
from core.adk_client import run_adk_prompt
from core.license import LicenseManager
from mcp_servers.setup import logger
from mcp_servers.utils import _send_notification


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
    from mcp_servers.utils import _get_user_channel_info
    db = SessionLocal()
    try:
        # Re-fetch work inside this session to avoid detached-instance issues
        work = db.query(models.RegularWork).filter(models.RegularWork.id == regular_work_id).first()
        if not work:
            return

        # Resolve channel/recipient for this user
        channel = work.channel
        recipient = work.recipient
        if not channel:
            channel, recipient = _get_user_channel_info(user_id, db)

        app_name = os.getenv("ADK_APP_NAME", "costaff_agent")
        session_id = f"rwork_{regular_work_id}_{user_id[:8]}"
        spec = work.spec
        if channel and recipient:
            spec += f"\n\n(System Note: This is a scheduled regular work. Deliver your output to the user via {channel}. Do NOT call send_message_now for this recipient.)"

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

            if channel and recipient and not work.silent:
                await _send_notification(channel, recipient, result_text, session_id)

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
