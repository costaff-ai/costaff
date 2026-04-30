from .telegram import send_telegram_notification, send_telegram_document
from .discord import send_discord_notification
from .email_notifier import send_email_notification
from .line_notifier import send_line_notification

def send_proactive_notification(user_id: str, message: str, session_id: str = None):
    """
    Intelligently routes a proactive notification to the correct platform
    based on the session_id or user metadata.
    """
    if session_id:
        if session_id.startswith("tg_"):
            return send_telegram_notification(user_id, message)
        elif session_id.startswith("dc_"):
            return send_discord_notification(user_id, message, session_id=session_id)
        elif session_id.startswith("line_"):
            return send_line_notification(user_id, message)
    
    # Fallback: try Telegram as default
    return send_telegram_notification(user_id, message)
