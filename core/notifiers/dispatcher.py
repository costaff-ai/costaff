"""Cross-channel notification dispatcher.

Resolves an opaque recipient (which may be a hashed_id or a session_id)
through the IdentityMap, picks the right notifier (telegram / discord /
line) based on the requested channel, and forwards the message.

Used by the MCP scheduler executors and any other place that needs to
push a system-generated message to a user without going through the
agent loop.
"""
import asyncio

from core import models
from core.database import SessionLocal
from core.notifiers.discord import send_discord_file, send_discord_notification
from core.notifiers.line_notifier import send_line_notification
from core.notifiers.slack_notifier import send_slack_file, send_slack_notification
from core.notifiers.telegram import (
    extract_file_paths,
    send_telegram_document,
    send_telegram_notification,
)
from core.notifiers.webchat import send_webchat_file, send_webchat_notification


async def dispatch_notification(
    channel: str,
    recipient: str,
    message: str,
    session_id: str = None,
) -> None:
    """Resolve identity mapping and dispatch notification to the correct channel.

    - channel is a free-form string; routing matches case-insensitive substrings:
      tg/telegram → Telegram, dc/discord → Discord, line → LINE,
      slack → Slack,
      webchat/webent/web_ → WebChat Enterprise (HTTP push to its internal endpoint).
    - recipient may be a hashed_id, a session_id, or already a real platform
      id; the IdentityMap is consulted to translate the first two.
    """
    db = SessionLocal()
    try:
        target_id = recipient
        mapping = db.query(models.IdentityMap).filter(
            (models.IdentityMap.hashed_id == target_id)
            | (models.IdentityMap.session_id == target_id)
        ).first()
        if mapping:
            target_id = mapping.real_id

        # The per-channel send helpers below do BLOCKING httpx calls (Slack
        # file upload times out at 60s, Telegram document at 30s). This is an
        # async function, so calling them directly would freeze the whole
        # event loop — every other task's progress panel / executor / queue
        # poll stalls. Offload each to a worker thread. (LINE is already async.)
        chan = (channel or "").lower()
        if "tg" in chan or "telegram" in chan:
            await asyncio.to_thread(send_telegram_notification, target_id, message)
            # Attach any /app/data/... files referenced in the message.
            # `send_message_now` already does this; without mirroring it here
            # the async callback path (BA / coding completion via project_task
            # executor) delivers prose only and the user never receives the
            # PDF / CSV the agent produced.
            for fp in extract_file_paths(message):
                await asyncio.to_thread(send_telegram_document, target_id, fp)
        elif "dc" in chan or "discord" in chan:
            await asyncio.to_thread(
                send_discord_notification, target_id, message, session_id=session_id)
            # Same rationale as the Telegram branch — without this the
            # async callback path delivers prose only and the user never
            # receives the PDF / CSV the agent produced.
            for fp in extract_file_paths(message):
                await asyncio.to_thread(
                    send_discord_file, target_id, fp, session_id=session_id)
        elif "slack" in chan:
            await asyncio.to_thread(send_slack_notification, target_id, message)
            for fp in extract_file_paths(message):
                await asyncio.to_thread(send_slack_file, target_id, fp)
        elif "line" in chan:
            await send_line_notification(target_id, message)
        elif "webchat" in chan or "webent" in chan or "web_" in chan:
            # `recipient` here is the hashed_id (post-IdentityMap translation
            # above maps recipients to real_id, but WebChat resolves its own
            # session_id from session_id arg + hashed_id fallback). Pass the
            # original recipient so the WebChat side can look up identity_maps.
            await asyncio.to_thread(
                send_webchat_notification, recipient, message, session_id=session_id)
            # Mirror the Telegram behaviour — extract /app/data/... paths
            # from the message body and ship each as an agent_file frame so
            # the user can actually download what the agent produced.
            for fp in extract_file_paths(message):
                await asyncio.to_thread(
                    send_webchat_file, recipient, fp, session_id=session_id)
    finally:
        db.close()
