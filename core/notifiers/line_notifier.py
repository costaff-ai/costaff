import httpx
import logging
import os
from dotenv import load_dotenv

from core.notifiers.formatters import md_to_plain

load_dotenv()
logger = logging.getLogger(__name__)


async def send_line_notification(user_id: str, message: str):
    """Sends a push notification message via LINE Messaging API.

    Args:
        user_id (str): The LINE User ID or Group ID.
        message (str): The text message to send.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN not found")
        # Return False (not None): the dispatcher treats a falsy-but-not-False
        # result as success, so a bare `return` here would mark an undelivered
        # message as sent and skip the retry outbox.
        return False

    # LINE text messages render no Markdown — strip every sigil so the
    # user does NOT see raw '##' / '**' / backticks. See
    # core/notifiers/formatters.py for the conversion table.
    message = md_to_plain(message)

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("LINE notification failed")
            return False
