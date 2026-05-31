from core import models
from core.database import SessionLocal
from core.notifiers.telegram import send_telegram_notification
from core.notifiers.line_notifier import send_line_notification
from core.notifiers.discord import send_discord_notification
from core.notifiers.email_notifier import send_email_notification
from mcp_servers.setup import logger


async def execute_reminder(reminder_id: str):
    """Send a one-time scheduled reminder message to the user."""
    db = SessionLocal()
    try:
        reminder = db.query(models.Reminder).filter(models.Reminder.id == reminder_id).first()
        if not reminder or reminder.status != "pending":
            return

        # Authoritative channel: resolve from the user's IdentityMap (where the
        # user actually is), not the stored channel — which create_reminder may
        # have defaulted to "telegram" before webchat was a recognised branch.
        # Mirrors execute_regular_work. dispatch_notification handles every
        # channel (telegram / discord / line / email / webchat-enterprise) plus
        # the hashed_id → real_id resolution, so we no longer dispatch by hand.
        from mcp_servers.task_helpers import get_user_channel_info
        from core.notifiers.dispatcher import dispatch_notification

        chan = (reminder.channel or "").lower()
        recipient = reminder.recipient or reminder.user_id
        resolved_chan, resolved_recipient = get_user_channel_info(reminder.user_id, db)
        if resolved_chan:
            chan = resolved_chan
            recipient = resolved_recipient or recipient

        logger.info(f"Sending reminder {reminder_id} via {chan}")

        success = False
        try:
            await dispatch_notification(chan, recipient, reminder.message, session_id=reminder.session_id)
            success = True
        except Exception as e:
            logger.error(f"Reminder send error {reminder_id}: {e}")

        reminder.status = "sent" if success else "failed"
        db.commit()

    except Exception as e:
        logger.error(f"execute_reminder failed {reminder_id}: {e}")
    finally:
        db.close()
