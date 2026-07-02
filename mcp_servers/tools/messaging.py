import asyncio
import os
import uuid
from datetime import datetime
from typing import Optional

from core import models
from core.database import SessionLocal
from core.notifiers.telegram import (
    extract_file_paths as _extract_file_paths,
    send_telegram_document,
    send_telegram_notification,
)
from core.notifiers.line_notifier import send_line_notification
from core.notifiers.discord import send_discord_file, send_discord_notification
from core.notifiers.slack_notifier import send_slack_file, send_slack_notification
from mcp_servers.setup import mcp, tz


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
    elif "slack" in chan: chan = "slack"
    elif "line" in chan: chan = "line"
    elif "web" in chan: chan = "webchat"
    elif chan == "default" or not chan:
        if session_id:
            # `discord_` / `dc_` both accepted — the channel adapter's
            # platform_prefix is "discord", legacy sessions used "dc".
            if session_id.startswith("tg_"): chan = "telegram"
            elif session_id.startswith(("dc_", "discord_")): chan = "discord"
            elif session_id.startswith("slack_"): chan = "slack"
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

    # The telegram/discord/slack senders do BLOCKING httpx calls (file upload
    # up to 60s). This is an async MCP tool running on the core event loop, so
    # calling them directly would freeze every other task's panel/executor/
    # queue poll. Offload each to a worker thread. (LINE is already async.)
    success = False
    if chan == "telegram":
        success = await asyncio.to_thread(
            send_telegram_notification, target_id, body, session_id=session_id)
        for fp in _extract_file_paths(body):
            await asyncio.to_thread(send_telegram_document, target_id, fp)
    elif chan == "discord":
        success = await asyncio.to_thread(
            send_discord_notification, target_id, body, session_id=session_id)
        for fp in _extract_file_paths(body):
            await asyncio.to_thread(send_discord_file, target_id, fp, session_id=session_id)
    elif chan == "slack":
        success = await asyncio.to_thread(send_slack_notification, target_id, body)
        for fp in _extract_file_paths(body):
            await asyncio.to_thread(send_slack_file, target_id, fp)
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
