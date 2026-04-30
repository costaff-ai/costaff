import os
import json
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken

from core import models
from core.database import SessionLocal
from core.notifiers.telegram import send_telegram_notification
from core.notifiers.line_notifier import send_line_notification
from core.notifiers.discord import send_discord_notification
from mcp_servers.core import logger


# ---------------------------------------------------------------------------
# Encryption Helpers
# ---------------------------------------------------------------------------

def _get_fernet() -> Optional[Fernet]:
    key = os.getenv("API_HEADERS_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None

def _decrypt_headers(encrypted: str) -> dict:
    f = _get_fernet()
    if f:
        try:
            return json.loads(f.decrypt(encrypted.encode()).decode())
        except InvalidToken:
            pass
    try:
        return json.loads(encrypted)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# SSRF Protection
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def _is_safe_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname
        if not host:
            return False
        for item in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(item[4][0])
            if any(ip in net for net in _PRIVATE_NETWORKS):
                return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Notification Helper
# ---------------------------------------------------------------------------

async def _send_notification(channel: str, recipient: str, message: str, session_id: str = None):
    """Resolve identity mapping and dispatch notification to the correct channel."""
    db = SessionLocal()
    try:
        target_id = recipient
        mapping = db.query(models.IdentityMap).filter(
            (models.IdentityMap.hashed_id == target_id) |
            (models.IdentityMap.session_id == target_id)
        ).first()
        if mapping:
            target_id = mapping.real_id

        chan = (channel or "").lower()
        if "tg" in chan or "telegram" in chan:
            send_telegram_notification(target_id, message)
        elif "dc" in chan or "discord" in chan:
            send_discord_notification(target_id, message, session_id=session_id)
        elif "line" in chan:
            await send_line_notification(target_id, message)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Project Task Helpers
# ---------------------------------------------------------------------------

def _get_user_channel_info(user_id: str, db) -> tuple:
    """
    Look up the user's primary notification channel from IdentityMap.
    Returns (channel, hashed_id) or (None, None) if not found.
    channel is derived from the session_id prefix: tg_ / dc_ / line_
    recipient is always the hashed_id so _send_notification can resolve it.
    """
    mapping = (
        db.query(models.IdentityMap)
        .filter(models.IdentityMap.hashed_id == user_id)
        .order_by(models.IdentityMap.created_at.desc())
        .first()
    )
    if not mapping:
        return None, None
    sid = mapping.session_id or ""
    if sid.startswith("tg_"):
        return "telegram", user_id
    elif sid.startswith("dc_"):
        return "discord", user_id
    elif sid.startswith("line_"):
        return "line", user_id
    elif sid.startswith("web_"):
        return "webchat", user_id
    return None, None


def _build_task_spec(task, db) -> str:
    """
    Build a context-enriched execution spec for costaff_agent.
    Prepends Epic and Story titles, routing hint, and PROGRESS_CONTEXT for live notifications.
    """
    lines = []

    if task.epic_id:
        epic = db.query(models.Epic).filter(models.Epic.id == task.epic_id).first()
        if epic:
            lines.append(f"[Project: {epic.title}]")
            if epic.description:
                lines.append(f"Project goal: {epic.description}")

    if task.story_id:
        story = db.query(models.Story).filter(models.Story.id == task.story_id).first()
        if story:
            lines.append(f"[Story: {story.title}]")
            if story.description:
                lines.append(f"Story context: {story.description}")

    lines.append(f"[Task: {task.title}]")
    if task.spec:
        lines.append(task.spec)

    preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "English")

    if task.assigned_agent and task.assigned_agent != "costaff_agent":
        lines.append(
            f"\n[DELEGATION INSTRUCTIONS — READ CAREFULLY]\n"
            f"This task is assigned to: {task.assigned_agent}\n"
            f"You MUST:\n"
            f"1. Call add_task_comment(task_id=\"{task.id}\", comment_type=\"note\") with an implementation plan BEFORE delegating.\n"
            f"   Format the plan as:\n"
            f"   ## Implementation Plan\n"
            f"   - **Goal**: <what this task needs to achieve>\n"
            f"   - **Steps**:\n"
            f"     1. <step>\n"
            f"   - **Expected Output**: <files, tables, reports, etc.>\n"
            f"2. Call {task.assigned_agent} via A2A tool, passing the FULL task spec above (including PROGRESS_CONTEXT).\n"
            f"3. WAIT for {task.assigned_agent} to return its COMPLETE output (e.g. file path, report content, etc.).\n"
            f"4. If {task.assigned_agent} returns an error, call add_task_comment(task_id=\"{task.id}\", comment_type=\"issue\") with:\n"
            f"   ## ❌ Error Occurred\n"
            f"   - **Error Type**: <type>\n"
            f"   - **Error Message**: <full message>\n"
            f"   - **Location**: <which step>\n"
            f"   - **Resolution**: <how it was fixed or what to explain>\n"
            f"5. Your FINAL response (which becomes the completion comment) MUST follow this format:\n"
            f"   ## ✅ Task Complete\n"
            f"   ### Use Cases\n"
            f"   - <how this output will be used>\n"
            f"   ### Acceptance Criteria\n"
            f"   - ✅ <criterion 1>: <how it was met>\n"
            f"   - ✅ <criterion 2>: <how it was met>\n"
            f"   ### Output\n"
            f"   - <concrete deliverables: file paths, tables, report locations, etc.>\n"
            f"   Do NOT return 'I have delegated this task' or any delegation acknowledgment as your final response.\n"
            f"   Do NOT use send_message_now to say you delegated — only send it if {task.assigned_agent} produces an actual result to share.\n"
            f"The task is NOT done until you receive and relay {task.assigned_agent}'s actual deliverable."
        )

        lines.append(f"\n(System: Autonomous project task ID={task.id}. Execute it. Respond in {preferred_lang}.)")
    # Resolve channel/recipient for PROGRESS_CONTEXT so coding_agent can send live updates
    channel = task.channel
    recipient = task.recipient
    if not channel:
        channel, recipient = _get_user_channel_info(task.user_id, db)

    if channel and recipient:
        task_session_id = f"task_{task.id}"
        lines.append(
            f"\n[PROGRESS_CONTEXT]\n"
            f"user_id={task.user_id}\n"
            f"channel={channel}\n"
            f"session_id={task_session_id}"
        )

    return "\n".join(lines)
