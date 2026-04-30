import httpx
import logging
import os
from dotenv import load_dotenv
from core import models
from core.database import SessionLocal

load_dotenv()
logger = logging.getLogger(__name__)

def send_telegram_notification(recipient_id: str, message: str, session_id: str = None):
    """Sends a notification message to a Telegram chat (Synchronous)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found")
        return False

    final_recipient = recipient_id
    db = SessionLocal()
    try:
        # 1. Try resolving via session_id if provided (Highest priority for accuracy)
        if session_id:
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.session_id == session_id).first()
            if mapping:
                final_recipient = mapping.real_id
                logger.debug(f"Resolved session_id {session_id} → real_id {final_recipient}")

        # 2. Fallback to resolving via hashed_id if recipient_id is not a digit
        if not str(final_recipient).isdigit():
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == final_recipient).first()
            if mapping:
                final_recipient = mapping.real_id
                logger.debug(f"Resolved hashed_id → real_id {final_recipient}")
            else:
                logger.warning(f"Could not resolve hashed_id {final_recipient} to a real_id")
    finally:
        db.close()

    # Telegram HTML mode does not support <br> — replace with newline
    import re
    message = re.sub(r'<br\s*/?>', '\n', message, flags=re.IGNORECASE)

    # Telegram max message length is 4096 chars
    MAX_LEN = 4096
    if len(message) > MAX_LEN:
        message = message[:MAX_LEN - 100] + "\n\n...(message too long, truncated)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": final_recipient, "text": message, "parse_mode": "HTML"}

    logger.info(f"Sending Telegram notification to {final_recipient}")
    with httpx.Client(timeout=10.0) as client:
        try:
            response = client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"HTML send failed ({response.status_code}), retrying as plain text")
                payload.pop("parse_mode")
                response = client.post(url, json=payload)
                if response.status_code != 200:
                    logger.error(f"Plain text send also failed ({response.status_code}): {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram notification exception: {e}")
            return False

def send_telegram_document(recipient_id: str, file_path: str, caption: str = None):
    """Sends a document file to a Telegram chat."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not os.path.exists(file_path):
        return False

    final_recipient = recipient_id
    if not recipient_id.isdigit():
        db = SessionLocal()
        try:
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == recipient_id).first()
            if mapping:
                final_recipient = mapping.real_id
        finally:
            db.close()

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with httpx.Client(timeout=30.0) as client:
        try:
            with open(file_path, "rb") as f:
                files = {"document": (os.path.basename(file_path), f)}
                data = {"chat_id": final_recipient}
                if caption:
                    data["caption"] = caption
                res = client.post(url, data=data, files=files)
                return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram document: {e}")
            return False
