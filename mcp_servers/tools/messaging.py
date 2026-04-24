import re
import os
import uuid
from datetime import datetime
from typing import Optional

from src.core import models
from src.core.database import SessionLocal
from src.core.notifiers.telegram import send_telegram_notification, send_telegram_document
from src.core.notifiers.line_notifier import send_line_notification
from src.core.notifiers.discord import send_discord_notification
from mcp_servers.core import mcp, tz

_FILE_EXTS = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"
_ABS_PATH_RE = re.compile(r"(/app/data/[\w./-]+\.(?:" + _FILE_EXTS + r"))", re.IGNORECASE)


def _extract_file_paths(text: str) -> list[str]:
    """Extract /app/data/... file paths from a message body."""
    seen = set()
    result = []
    for p in _ABS_PATH_RE.findall(text):
        if p not in seen and os.path.isfile(p):
            seen.add(p)
            result.append(p)
    return result


@mcp.tool()
async def send_message_now(
    channel: str, recipient: str,
    body: str = None, subject: str = None,
    app_name: str = "costaff_agent",
    user_id: str = None, session_id: str = None
) -> str:
    """Immediately sends a message to the user via the specified channel."""
    if not body or not body.strip():
        return "Error: body is required."

    chan = (channel or "").lower()
    if "tg" in chan or "telegram" in chan: chan = "telegram"
    elif "dc" in chan or "discord" in chan: chan = "discord"
    elif "line" in chan: chan = "line"
    elif "web" in chan: chan = "webchat"
    elif chan == "default" or not chan:
        if session_id:
            if session_id.startswith("tg_"): chan = "telegram"
            elif session_id.startswith("dc_"): chan = "discord"
            elif session_id.startswith("line_"): chan = "line"
            elif session_id.startswith("web_"): chan = "webchat"
            else: chan = "telegram"  # fallback
        else:
            chan = "telegram" # fallback

    db = SessionLocal()
    try:
        target_id = recipient
        mapping = db.query(models.IdentityMap).filter(
            (models.IdentityMap.hashed_id == target_id) |
            (models.IdentityMap.session_id == target_id)
        ).first()
        if mapping:
            target_id = mapping.real_id
    finally:
        db.close()

    success = False
    if chan == "telegram":
        success = send_telegram_notification(target_id, body, session_id=session_id)
        for fp in _extract_file_paths(body):
            send_telegram_document(target_id, fp)
    elif chan == "discord": success = send_discord_notification(target_id, body, session_id=session_id)
    elif chan == "line": success = await send_line_notification(target_id, body)
    elif chan == "webchat":
        # Webchat uses the regular notification flow (events)
        # Here we just mark as success if we found a valid session
        success = True if session_id else False

    # Log as a completed reminder
    db = SessionLocal()
    try:
        log = models.Reminder(
            id=str(uuid.uuid4()),
            user_id=user_id or "unknown",
            session_id=session_id or "unknown",
            app_name=app_name or "costaff_agent",
            message=body,
            run_at=datetime.now(tz),
            channel=chan,
            recipient=recipient,
            status="sent" if success else "failed",
            created_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
    finally:
        db.close()

    return "Sent." if success else "Failed."
