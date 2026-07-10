"""Cross-channel notification dispatcher.

Resolves an opaque recipient (which may be a hashed_id or a session_id)
through the IdentityMap, picks the right notifier (telegram / discord /
line) based on the requested channel, and forwards the message.

Used by the MCP scheduler executors and any other place that needs to
push a system-generated message to a user without going through the
agent loop.

Delivery is guaranteed as far as the outbox: if the primary text push
fails (channel 5xx, missing secret, network), the message is enqueued to
`notification_outbox` and a background loop retries with exponential
backoff. A task result is therefore never lost just because a push
happened to fail once.
"""
import asyncio
import logging

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

logger = logging.getLogger(__name__)


async def _send_to_channel(
    channel: str, recipient: str, message: str, session_id: str = None,
) -> bool:
    """Send one message to `channel`, returning True iff the text push
    succeeded. Files are best-effort and don't affect the return value.

    The per-channel helpers already return a bool (False, not raise, on
    failure). This function is the single delivery primitive shared by the
    live dispatch path and the outbox retry loop.
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
    finally:
        db.close()

    # The per-channel send helpers do BLOCKING httpx calls (Slack file upload
    # times out at 60s, Telegram document at 30s). This is an async function,
    # so calling them directly would freeze the whole event loop — every other
    # task's progress panel / executor / queue poll stalls. Offload each to a
    # worker thread. (LINE is already async.)
    chan = (channel or "").lower()
    ok = False
    if "tg" in chan or "telegram" in chan:
        ok = await asyncio.to_thread(send_telegram_notification, target_id, message)
        for fp in extract_file_paths(message):
            await asyncio.to_thread(send_telegram_document, target_id, fp)
    elif "dc" in chan or "discord" in chan:
        ok = await asyncio.to_thread(
            send_discord_notification, target_id, message, session_id=session_id)
        for fp in extract_file_paths(message):
            await asyncio.to_thread(
                send_discord_file, target_id, fp, session_id=session_id)
    elif "slack" in chan:
        ok = await asyncio.to_thread(send_slack_notification, target_id, message)
        for fp in extract_file_paths(message):
            await asyncio.to_thread(send_slack_file, target_id, fp)
    elif "line" in chan:
        ok = await send_line_notification(target_id, message)
    elif "webchat" in chan or "webent" in chan or "web_" in chan:
        # WebChat resolves its own session from session_id + hashed_id, so pass
        # the ORIGINAL recipient (not the IdentityMap-translated real_id).
        ok = await asyncio.to_thread(
            send_webchat_notification, recipient, message, session_id=session_id)
        for fp in extract_file_paths(message):
            await asyncio.to_thread(
                send_webchat_file, recipient, fp, session_id=session_id)
    else:
        logger.warning("[dispatch] unknown channel %r — cannot deliver", channel)
        return False
    # Every notifier returns True only on a confirmed send. Require exactly
    # that — an earlier `ok is not False` swallowed LINE's None-on-missing-
    # token as success, silently losing the message and skipping the outbox.
    return ok is True


async def dispatch_notification(
    channel: str,
    recipient: str,
    message: str,
    session_id: str = None,
    enqueue_on_failure: bool = True,
) -> bool:
    """Resolve identity mapping and dispatch a notification to `channel`.

    Returns True if delivered. On failure the message is written to
    `notification_outbox` for background retry (unless `enqueue_on_failure`
    is False — the retry loop passes False to avoid re-enqueuing what it is
    already retrying). Never raises: a delivery failure becomes an outbox
    row, not an exception into the caller.

    Routing matches case-insensitive substrings: tg/telegram, dc/discord,
    slack, line, webchat/webent/web_. `recipient` may be a hashed_id,
    session_id, or a real platform id.
    """
    try:
        ok = await _send_to_channel(channel, recipient, message, session_id)
    except Exception as e:
        logger.exception("[dispatch] send raised for channel=%s", channel)
        ok = False
        if enqueue_on_failure:
            _enqueue(channel, recipient, message, session_id, error=str(e))
        return False
    if not ok and enqueue_on_failure:
        _enqueue(channel, recipient, message, session_id,
                 error="channel push returned failure")
    return ok


def _enqueue(channel: str, recipient: str, message: str,
             session_id: str = None, error: str = None) -> None:
    """Persist a failed notification for background retry. Best-effort:
    a broken DB here must not mask the original delivery attempt."""
    from datetime import datetime
    db = SessionLocal()
    try:
        db.add(models.NotificationOutbox(
            channel=channel, recipient=recipient, message=message,
            session_id=session_id, status="pending", attempts=0,
            next_attempt_at=datetime.utcnow(), last_error=error,
        ))
        db.commit()
        logger.warning(
            "[dispatch] enqueued failed notification to outbox "
            "(channel=%s): %s", channel, error,
        )
    except Exception:
        db.rollback()
        logger.exception("[dispatch] failed to enqueue notification to outbox")
    finally:
        db.close()
