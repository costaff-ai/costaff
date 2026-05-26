"""WebChat (Enterprise) channel notifier.

Sub-agent progress and completion messages go through the Manager's
notifier dispatcher; this module is the WebChat leaf of that fan-out.

The actual delivery is an HTTP POST to the WebChat Enterprise container's
`/api/internal/push` endpoint with a shared-secret header. WebChat then
forwards the payload to the user's live WebSocket (and stores it to its
chat_messages table for refresh persistence).

Both containers share the docker network `costaff_default`, so the URL
defaults to `http://costaff-channel-webchat-enterprise:80/api/internal/push`.
Override via env if the deployment names differ.

Fail-safe: never raises into the caller. A broken WebChat push must not
break task execution (mirrors core/notifiers/progress_panel's contract).
"""

import logging
import os

import httpx

from core import models
from core.database import SessionLocal

logger = logging.getLogger(__name__)

# These resolve at call time, NOT module import, so changing the env on a
# running container picks up without a rebuild.
def _push_url() -> str:
    return os.getenv(
        "WEBCHAT_ENT_PUSH_URL",
        "http://costaff-channel-webchat-enterprise:80/api/internal/push",
    )


def _shared_secret() -> str:
    return os.getenv("WEBCHAT_ENT_INTERNAL_SECRET", "")


def _resolve_session_id(recipient: str, session_id: str | None) -> str | None:
    """Return a session_id WebChat Enterprise can use to look up the
    conversation / user.

    Channel routing has already happened upstream — by the time this
    function runs, the dispatcher chose webchat. So we trust whatever
    `session_id` was passed (post-thread refactor this is the ADK
    session id stored on Conversation.adk_session_id). Falls back to an
    IdentityMap lookup by recipient (hashed_id) when no session_id was
    provided — typically Manager-side callbacks that only know the user.
    """
    if session_id:
        return session_id
    if not recipient:
        return None
    db = SessionLocal()
    try:
        mapping = (
            db.query(models.IdentityMap)
            .filter(models.IdentityMap.hashed_id == recipient)
            .order_by(models.IdentityMap.created_at.desc())
            .first()
        )
        if mapping and mapping.session_id:
            return mapping.session_id
    except Exception:
        logger.exception("[webchat] session resolve failed")
    finally:
        db.close()
    return None


def _post(payload: dict) -> bool:
    """Shared HTTP POST to /api/internal/push. Returns True on 2xx."""
    secret = _shared_secret()
    if not secret:
        logger.warning("[webchat] WEBCHAT_ENT_INTERNAL_SECRET not set; skipping push")
        return False
    headers = {"X-Internal-Token": secret, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(_push_url(), json=payload, headers=headers)
        if r.status_code >= 400:
            logger.warning(
                "[webchat] push %s rejected: %s %s",
                _push_url(), r.status_code, r.text[:200],
            )
            return False
        return True
    except Exception as e:
        logger.warning("[webchat] push failed: %s", e)
        return False


def send_webchat_notification(
    recipient: str,
    message: str,
    session_id: str | None = None,
    agent: str | None = None,
    task_id: str | None = None,
    step: str | None = None,
    status: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Push a text message to the WebChat Enterprise channel.

    `conversation_id` (when known — e.g. injected by Manager into
    PROGRESS_CONTEXT and threaded through executor / sub-agent tools)
    pins the push to one thread. Without it WebChat fans out to every
    thread tab the user has open, which is louder than ideal but lands
    somewhere visible."""
    sid = _resolve_session_id(recipient, session_id)
    if not sid and not recipient:
        logger.warning("[webchat] no session_id or recipient — dropping")
        return False
    return _post({
        "session_id": sid,
        "hashed_id": recipient if not sid else None,
        "conversation_id": conversation_id,
        "text": message,
        "agent": agent,
        "task_id": task_id,
        "step": step,
        "status": status,
    })


def send_webchat_file(
    recipient: str,
    file_path: str,
    session_id: str | None = None,
    agent: str | None = None,
    task_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Deliver an /app/data/... file to the WebChat user. The WebChat side
    issues a download token bound to this user and pushes an agent_file
    frame the chat renders as a download card."""
    sid = _resolve_session_id(recipient, session_id)
    if not sid and not recipient:
        return False
    return _post({
        "session_id": sid,
        "hashed_id": recipient if not sid else None,
        "conversation_id": conversation_id,
        "text": "",
        "file_path": file_path,
        "agent": agent,
        "task_id": task_id,
    })
