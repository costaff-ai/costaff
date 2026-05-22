import httpx
import logging
import os
import re
from dotenv import load_dotenv
from core import models
from core.database import SessionLocal
from core.notifiers.result_envelope import parse_result_envelope

load_dotenv()
logger = logging.getLogger(__name__)


_FILE_EXTS = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"
_ABS_PATH_RE = re.compile(r"(/app/data/[\w./-]+\.(?:" + _FILE_EXTS + r"))", re.IGNORECASE)

# Markdown -> Telegram HTML conversion. Telegram's HTML parse_mode supports
# a narrow set (<b>, <i>, <u>, <s>, <code>, <pre>, <a href>, <blockquote>)
# and notably has NO <h1..h6>. Agents (and specialist completion comments
# from build_task_spec) routinely produce '## heading' / '**bold**' / '`code`'
# Markdown that Telegram renders as literal text — so callbacks like the
# project_task executor's synthetic-callback dispatch arrive as raw '##'.
# Convert at the notifier boundary so every caller (executor, send_message_now,
# Manager replies that forgot to convert) gets the same result.

_MD_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*$', re.MULTILINE)
_MD_BOLD_RE = re.compile(r'\*\*(.+?)\*\*', re.DOTALL)
_MD_CODE_INLINE_RE = re.compile(r'`([^`\n]+?)`')
_MD_CODE_FENCE_RE = re.compile(r'```(?:\w+)?\n(.*?)```', re.DOTALL)
_MD_BULLET_RE = re.compile(r'^(\s*)-\s+', re.MULTILINE)
_RESULT_TAG_RE = re.compile(r'\s*\[RESULT_(?:START|END)\]\s*')


def md_to_telegram_html(text: str) -> str:
    """Convert agent-style Markdown to Telegram HTML.

    Handles the patterns we actually see in the wild (verified 2026-05-22
    on the sin/cos EDA run): `## heading`, `### heading`, `**bold**`,
    `` `code` ``, fenced ```code``` blocks, leading `- bullet`, plus
    strips `[RESULT_START]` / `[RESULT_END]` envelope markers.

    Idempotent on Telegram-HTML input (raw `<b>...</b>` etc. has no
    Markdown sigils, so the regex passes leave it untouched).

    NOTE: we do NOT convert `*italic*` or `_italic_` — single-asterisk and
    single-underscore patterns collide with real content (file paths like
    `costaff_agent`, math like `2*pi`) too often to be safe without a real
    Markdown parser.
    """
    if not text:
        return text
    out = _RESULT_TAG_RE.sub('', text)
    # Fenced code blocks first (so inline-code regex doesn't mangle them).
    out = _MD_CODE_FENCE_RE.sub(lambda m: f"<pre>{m.group(1).rstrip()}</pre>", out)
    out = _MD_HEADING_RE.sub(r'<b>\1</b>', out)
    out = _MD_BOLD_RE.sub(r'<b>\1</b>', out)
    out = _MD_CODE_INLINE_RE.sub(r'<code>\1</code>', out)
    out = _MD_BULLET_RE.sub(r'\1• ', out)
    return out


def extract_file_paths(text: str) -> list[str]:
    """Extract /app/data/... absolute file paths from a message body.

    Two-stage lookup:
    1. If the message contains a structured [RESULT_START]...[RESULT_END]
       envelope with an explicit `files:` list, trust that list. This
       eliminates regex false-positives (paths mentioned in prose that
       aren't actual outputs) and false-negatives (paths with unusual
       characters the regex misses).
    2. Otherwise, fall back to regex matching `/app/data/<...>.<ext>`
       across the whole text. This preserves the legacy behaviour for
       sub-agents that haven't migrated to the structured envelope yet.

    In both stages, results are de-duplicated and filtered to files that
    actually exist on disk — so a hallucinated path never gets attached.

    Used by both `send_message_now` (manager core MCP tool) and
    `dispatch_notification` (async callback executor).
    """
    if not text:
        return []

    seen: set[str] = set()
    result: list[str] = []

    # Stage 1: structured envelope (preferred)
    envelope = parse_result_envelope(text)
    if envelope.structured and envelope.files:
        for p in envelope.files:
            if p in seen:
                continue
            seen.add(p)
            if os.path.isfile(p):
                result.append(p)
        # If the structured envelope listed files but none of them exist,
        # do NOT fall back to regex — the agent claimed those specific
        # files and they're missing, attaching unrelated regex hits would
        # confuse the user. Return empty.
        return result

    # Stage 2: legacy regex fallback
    for p in _ABS_PATH_RE.findall(text):
        if p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p):
            result.append(p)
    return result

def send_telegram_notification(recipient_id: str, message: str, session_id: str = None):
    """Sends a notification message to a Telegram chat (Synchronous).

    When the session has a recorded `last_message_id` (set by the channel
    runtime on every inbound message), the outgoing notification quotes
    that message via Telegram's `reply_parameters` so async callbacks land
    as a reply to the user's original question rather than as a floating
    new message.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found")
        return False

    final_recipient = recipient_id
    reply_to_message_id: int | None = None
    db = SessionLocal()
    try:
        # 1. Try resolving via session_id if provided (Highest priority for accuracy)
        if session_id:
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.session_id == session_id).first()
            if mapping:
                final_recipient = mapping.real_id
                logger.debug(f"Resolved session_id {session_id} → real_id {final_recipient}")
                if mapping.last_message_id:
                    try:
                        reply_to_message_id = int(mapping.last_message_id)
                    except (TypeError, ValueError):
                        pass

        # 2. Fallback to resolving via hashed_id if recipient_id is not a digit
        if not str(final_recipient).isdigit():
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == final_recipient).first()
            if mapping:
                final_recipient = mapping.real_id
                logger.debug(f"Resolved hashed_id → real_id {final_recipient}")
                if reply_to_message_id is None and mapping.last_message_id:
                    try:
                        reply_to_message_id = int(mapping.last_message_id)
                    except (TypeError, ValueError):
                        pass
            else:
                logger.warning(f"Could not resolve hashed_id {final_recipient} to a real_id")
    finally:
        db.close()

    # Convert Markdown (##/###/**bold**/`code`/- bullets) to the Telegram
    # HTML subset before sending — Telegram does NOT parse Markdown under
    # parse_mode=HTML, so raw '## heading' would render literally.
    message = md_to_telegram_html(message)

    # Telegram HTML mode does not support <br> — replace with newline
    message = re.sub(r'<br\s*/?>', '\n', message, flags=re.IGNORECASE)

    # Telegram max message length is 4096 chars
    MAX_LEN = 4096
    if len(message) > MAX_LEN:
        message = message[:MAX_LEN - 100] + "\n\n...(message too long, truncated)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": final_recipient, "text": message, "parse_mode": "HTML"}
    if reply_to_message_id:
        # allow_sending_without_reply: if the target message was deleted, the
        # server still sends the new message (without quoting) instead of 400.
        payload["reply_parameters"] = {
            "message_id": reply_to_message_id,
            "allow_sending_without_reply": True,
        }

    logger.info(f"Sending Telegram notification to {final_recipient} (reply_to={reply_to_message_id})")
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
        except Exception:
            logger.exception("Telegram notification failed")
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
        except Exception:
            logger.exception("Failed to send Telegram document")
            return False
