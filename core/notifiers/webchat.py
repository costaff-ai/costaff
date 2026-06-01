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


# A valid session_id starts with a known channel prefix. Sub-agent LLMs
# have been observed passing the raw hashed_id (`4d0d9234bc031246`) or a
# bare ADK UUID into the session_id slot — those don't match anything on
# WebChat Enterprise's resolver and progress goes silent. We treat them
# as "missing" and fall through to the IdentityMap lookup.
_VALID_SESSION_PREFIXES = ("tg_", "dc_", "line_", "web_", "webent_")


def _resolve_session_id(recipient: str, session_id: str | None) -> str | None:
    """Return a session_id WebChat Enterprise can use to look up the
    conversation / user.

    Channel routing has already happened upstream — by the time this
    function runs, the dispatcher chose webchat. So we trust a
    `session_id` that *looks* like one (has a channel prefix); otherwise
    we treat it as missing and look up via IdentityMap by recipient
    (hashed_id). This second case covers both pure "session_id omitted"
    callbacks AND the more common "sub-agent LLM stripped the
    `webent_` prefix" failure mode.
    """
    if session_id and session_id.startswith(_VALID_SESSION_PREFIXES):
        return session_id
    # Live progress (report_step / panel_step) arrives with session_id =
    # `task_<task_id>` — that's the Telegram panel key, NOT a conversation.
    # For WebChat Enterprise we must resolve it to the ORIGIN conversation's
    # adk_session_id (stored on the task by the Manager's session-pin
    # before_tool_callback). Without this the push has no real session, falls
    # through to "latest active conv", and live tool-call progress leaks into
    # whatever thread the user opened mid-task (e.g. pressing New).
    if session_id and session_id.startswith("task_"):
        task_id = session_id[len("task_"):]
        db = SessionLocal()
        try:
            task = (
                db.query(models.ProjectTask)
                .filter(models.ProjectTask.id == task_id)
                .first()
            )
            sid = getattr(task, "session_id", None) if task else None
            # Only use it if it's a real conversation session (UUID-ish), not
            # another task_/hash value.
            if sid and not sid.startswith("task_"):
                return sid
        except Exception:
            logger.exception("[webchat] task->session resolve failed")
        finally:
            db.close()
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


def _post_file(file_path: str, session_id: str | None, hashed_id: str | None,
               conversation_id: str | None = None, agent: str | None = None,
               task_id: str | None = None) -> bool:
    """Upload a file's BYTES to the enterprise `/api/internal/push-file`.

    Needed for the multi-machine federation: a remote CoStaff node's file
    lives on ITS disk, so the enterprise (on another host) can't serve a bare
    path. We stream the bytes; the enterprise saves them locally and issues a
    download token. Only used when WEBCHAT_ENT_PUSH_URL is set (remote node)."""
    secret = _shared_secret()
    if not secret:
        return False
    url = _push_url().rsplit("/push", 1)[0] + "/push-file"
    data = {k: v for k, v in {
        "session_id": session_id, "hashed_id": hashed_id,
        "conversation_id": conversation_id, "agent": agent, "task_id": task_id,
    }.items() if v}
    try:
        with open(file_path, "rb") as fh, httpx.Client(timeout=30.0) as client:
            r = client.post(
                url, data=data,
                files={"file": (os.path.basename(file_path), fh)},
                headers={"X-Internal-Token": secret},
            )
        if r.status_code >= 400:
            logger.warning("[webchat] push-file %s rejected: %s %s", url, r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        logger.warning("[webchat] push-file failed: %s", e)
        return False


def _extract_data_paths(text: str) -> list:
    """/app/data/... file paths with known extensions (ordered, de-duped)."""
    import re
    exts = r"pdf|docx|doc|pptx|ppt|md|txt|html|htm|png|jpg|jpeg|gif|webp|svg|csv|json|xlsx|xls|zip"
    pat = re.compile(rf"/app/data/[\w./\-]+\.(?:{exts})", re.IGNORECASE)
    return list(dict.fromkeys(pat.findall(text or "")))


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
    # Remote federation node: the enterprise host can't read THIS machine's
    # disk, so its in-text /app/data path extraction would find nothing.
    # Proactively upload the bytes of any referenced file so it still renders
    # as a download card alongside the text.
    if os.getenv("WEBCHAT_ENT_PUSH_URL"):
        for _p in _extract_data_paths(message):
            if os.path.exists(_p):
                _post_file(_p, sid, recipient if not sid else None,
                           conversation_id=conversation_id, agent=agent, task_id=task_id)
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
    # Remote federation node: upload the bytes (the enterprise can't read a
    # bare path on another machine's disk).
    if os.getenv("WEBCHAT_ENT_PUSH_URL") and os.path.exists(file_path):
        return _post_file(file_path, sid, recipient if not sid else None,
                          conversation_id=conversation_id, agent=agent, task_id=task_id)
    return _post({
        "session_id": sid,
        "hashed_id": recipient if not sid else None,
        "conversation_id": conversation_id,
        "text": "",
        "file_path": file_path,
        "agent": agent,
        "task_id": task_id,
    })
