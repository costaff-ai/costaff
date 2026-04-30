from src.core import models
from src.core.database import SessionLocal
from src.core.notifiers.telegram import send_telegram_notification
from src.core.notifiers.line_notifier import send_line_notification
from src.core.notifiers.discord import send_discord_notification
from src.core.notifiers.email_notifier import send_email_notification
from mcp_servers.core import logger


async def execute_reminder(reminder_id: str):
    """Send a one-time scheduled reminder message to the user."""
    db = SessionLocal()
    try:
        reminder = db.query(models.Reminder).filter(models.Reminder.id == reminder_id).first()
        if not reminder or reminder.status != "pending":
            return

        chan = (reminder.channel or "").lower()
        if "line" in chan:
            chan = "line"
        elif "discord" in chan or "dc" in chan:
            chan = "discord"
        elif "email" in chan:
            chan = "email"
        else:
            chan = "telegram"

        logger.info(f"Sending reminder {reminder_id} via {chan}")

        success = False
        try:
            db2 = SessionLocal()
            # Try recipient first; if it doesn't resolve to a real_id (e.g. LLM
            # accidentally stored a display name like "Simon"), fall back to user_id.
            target_id = reminder.recipient
            mapping = db2.query(models.IdentityMap).filter(
                (models.IdentityMap.hashed_id == target_id) |
                (models.IdentityMap.session_id == target_id)
            ).first()
            if not mapping and reminder.user_id and reminder.user_id != target_id:
                logger.warning(
                    f"Reminder {reminder_id}: recipient '{target_id}' not in IdentityMap, "
                    f"falling back to user_id '{reminder.user_id}'"
                )
                target_id = reminder.user_id
                mapping = db2.query(models.IdentityMap).filter(
                    (models.IdentityMap.hashed_id == target_id) |
                    (models.IdentityMap.session_id == target_id)
                ).first()
            if mapping:
                target_id = mapping.real_id
            db2.close()

            if chan == "telegram":
                success = send_telegram_notification(target_id, reminder.message)
            elif chan == "discord":
                success = send_discord_notification(target_id, reminder.message, session_id=reminder.session_id)
            elif chan == "line":
                success = await send_line_notification(target_id, reminder.message)
            elif chan == "email":
                success = send_email_notification(target_id, reminder.message, "CoStaff Reminder")
        except Exception as e:
            logger.error(f"Reminder send error {reminder_id}: {e}")

        reminder.status = "sent" if success else "failed"
        db.commit()

    except Exception as e:
        logger.error(f"execute_reminder failed {reminder_id}: {e}")
    finally:
        db.close()
