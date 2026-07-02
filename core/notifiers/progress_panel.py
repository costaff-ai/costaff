"""Live progress panel — one Telegram message per task, edited in place.

A sub-agent's tool callbacks POST step events to /api/progress_step (the
http_api shim, this same MCP-core process). This module keeps a per-task
panel (header + ordered tool steps), sends the FIRST Telegram message and
EDITS that same message on every subsequent step and on finalize, so the
user sees one self-updating status block instead of N spammed messages:

    [ Business Analysis Agent ] Working
    generate_chart - Done
    export_pdf - Doing..

A per-panel background ticker animates every still-"Doing" line with
cycling dots (Doing. → Doing.. → Doing... → Doing.) while the step runs,
since no callback fires between a tool's start and end. The ticker stops
itself when nothing is "Doing" and is cancelled on finalize.

Entirely fail-safe: nothing here may ever raise into the caller. A broken
panel must never affect task execution (the agent/executor wrap calls in
try/except too — this is the second belt).
"""
import asyncio
import html
import logging
import os
import re

import httpx

from core import models
from core.database import SessionLocal

logger = logging.getLogger("costaff-agent-engine")

# Breathing-dots tick interval (s). ~1.3s keeps it lively without
# tripping Telegram's edit rate limit (429 is handled benignly anyway).
_TICK = float(os.getenv("COSTAFF_PANEL_TICK", "1.3"))

# A section divider entry: ["\x00sec", text] — the sub-agent's
# send_message_now narration, folded into the panel as a header line
# with the following tool lines grouped under it.
_SEC = "\x00sec"
# Scrolling cap: keep the most recent N section blocks so a long task
# never overflows Telegram's 4096-char single-message limit.
_MAX_SECTIONS = int(os.getenv("COSTAFF_PANEL_MAX_SECTIONS", "6"))
_MAX_CHARS = int(os.getenv("COSTAFF_PANEL_MAX_CHARS", "3500"))

# Per-key in-process state. Key = the task session id ("task_<task_id>"),
# which both the agent callback (from PROGRESS_CONTEXT) and the executor
# finalize derive identically.
_PANELS: dict = {}
_LOCKS: dict = {}

_AGENT_DISPLAY = {
    "business_analysis_agent": "Business Analysis Agent",
    "coding_agent": "Coding Agent",
    "twinkle_hub_agent": "Twinkle Hub Agent",
}


def _is_telegram_channel(channel) -> bool:
    """True for the canonical 'telegram' / 'tg' and any prefixed variant
    such as 'telegram_costaff_bot' or 'tg_main'. The Manager LLM has been
    observed to set channel='telegram_<bot_suffix>' in dispatch_plan calls
    (2026-05-22, Iris EDA run), so the panel must accept the whole
    telegram-family rather than only the exact short forms."""
    ch = (channel or "").lower()
    return ch in ("telegram", "tg") or ch.startswith("telegram_") or ch.startswith("tg_")


def _is_webchat_channel(channel) -> bool:
    """Mirror of _is_telegram_channel for WebChat / WebChat Enterprise.
    Phase A doesn't do edit-in-place; each step is fan-out as a separate
    /api/internal/push call so the chat surface shows them inline."""
    ch = (channel or "").lower()
    return "webchat" in ch or "webent" in ch or ch.startswith("web_")


def _is_discord_channel(channel) -> bool:
    ch = (channel or "").lower()
    return ch in ("discord", "dc") or ch.startswith("discord_") or ch.startswith("dc_")


def _is_slack_channel(channel) -> bool:
    ch = (channel or "").lower()
    return ch == "slack" or ch.startswith("slack_")


def _panel_transport(channel) -> str | None:
    """Map a channel string to an edit-in-place panel transport.

    Telegram, Discord and Slack all support editing a sent message, so
    they share the same panel lifecycle and differ only in the HTTP
    send/edit pair. Returns None for channels without panel support."""
    if _is_telegram_channel(channel):
        return "telegram"
    if _is_discord_channel(channel):
        return "discord"
    if _is_slack_channel(channel):
        return "slack"
    return None


def _display_agent(agent: str) -> str:
    a = agent or ""
    return _AGENT_DISPLAY.get(a, (a or "Agent").replace("_", " ").title())


def _resolve_chat(recipient: str, session_id: str):
    """Resolve a real Telegram chat id from user_id/session via IdentityMap
    (same resolution send_telegram_notification uses). None on failure."""
    try:
        db = SessionLocal()
        try:
            if session_id:
                m = (db.query(models.IdentityMap)
                       .filter(models.IdentityMap.session_id == session_id).first())
                if m and m.real_id:
                    return str(m.real_id)
            if recipient:
                if str(recipient).isdigit():
                    return str(recipient)
                m = (db.query(models.IdentityMap)
                       .filter(models.IdentityMap.hashed_id == recipient).first())
                if m and m.real_id:
                    return str(m.real_id)
        finally:
            db.close()
    except Exception:
        logger.exception("[panel] chat resolve failed")
    return None


def _resolve_task_title(key: str) -> str:
    """The panel key is `task_<task_id>`; look up that task's title for
    the structured header. Empty on any failure (fail-safe)."""
    try:
        if not key or not key.startswith("task_"):
            return ""
        tid = key[len("task_"):]
        db = SessionLocal()
        try:
            t = (db.query(models.ProjectTask)
                   .filter(models.ProjectTask.id == tid).first())
            return (t.title or "").strip() if t else ""
        finally:
            db.close()
    except Exception:
        logger.exception("[panel] task title resolve failed")
        return ""


# At most this many tool lines shown per Action block (most recent).
_MAX_TOOLS_PER_SECTION = int(os.getenv("COSTAFF_PANEL_MAX_TOOLS", "3"))


def _render(state: dict) -> str:
    steps = state["steps"]
    nfail = sum(1 for e in steps if e[0] != _SEC and e[1] == "Failed")
    status = state["header"]
    if status == "Working":
        status = f"Working{'.' * (1 + state.get('phase', 0) % 3)}"
    elif status == "Done":
        status = f"Done · {nfail} failed (recovered)" if nfail else "Done"
    elif status == "Failed":
        status = f"Failed · {nfail} failed" if nfail else "Failed"
    title = state.get("task_title") or "—"
    lines = [
        f"[ {state['agent_disp']} ]",
        "-----",
        f"1. task: {title}",
        f"2. status: {status}",
        "-----",
        "",
        "Working Process:",
    ]
    # Group into [leading tool-run] then ([section] tool-run)*. Each block
    # shows only its most recent _MAX_TOOLS_PER_SECTION tool lines; a blank
    # line separates blocks.
    i = 0
    n = len(steps)
    first = True
    while i < n:
        if steps[i][0] == _SEC:
            if not first:
                lines.append("")
            lines.append(f"- {steps[i][1]}")
            first = False
            i += 1
        run = []
        while i < n and steps[i][0] != _SEC:
            run.append(steps[i])
            i += 1
        if run:
            for label, st in run[-_MAX_TOOLS_PER_SECTION:]:
                lines.append(f"  {label} - {st}")
            first = False
    return "\n".join(lines)


# Section text is normalized to a uniform "[Action] <substance>":
# strip the agent's own tag ([BA]/[Coding]/[Twinkle]…) and any leading
# status verb (Started:/Done —/Failed:/Selected) so every agent's
# narration reads identically in the panel.
_AGENT_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")
_VERB_RE = re.compile(r"^(started|done|failed|selected)\b\s*[:：—\-]*\s*", re.I)


def _normalize_section(text: str) -> str:
    t = (text or "").strip()
    t = _AGENT_TAG_RE.sub("", t, count=1)
    t = _VERB_RE.sub("", t, count=1).strip()
    return f"[Action] {t}" if t else "[Action]"


def _ensure_state(key, recipient, session_id, agent, transport="telegram") -> dict:
    state = _PANELS.get(key)
    if state is None:
        state = {
            "chat_id": _resolve_chat(recipient, session_id),
            "message_id": None, "steps": [],
            "agent_disp": _display_agent(agent),
            "task_title": _resolve_task_title(key),
            "header": "Working", "last_text": None,
            "phase": 0, "ticker": None,
            "transport": transport,
        }
        _PANELS[key] = state
    return state


def _trim(state: dict):
    """Scrolling cap: drop the oldest whole section blocks past
    _MAX_SECTIONS, then a hard char-budget fallback so the rendered
    panel always fits one Telegram message."""
    steps = state["steps"]
    sec = [i for i, e in enumerate(steps) if e[0] == _SEC]
    while len(sec) > _MAX_SECTIONS:
        del steps[:sec[1]]
        sec = [i for i, e in enumerate(steps) if e[0] == _SEC]
    while len(steps) > 1 and len(_render(state)) > _MAX_CHARS:
        steps.pop(0)


# Render the panel as a Telegram monospace block so the indented tool
# lines and the framed header align (proportional font would skew them).
# HTML parse_mode + <pre> only needs &<> escaped (robust vs MarkdownV2).
def _mono(text: str) -> str:
    return f"<pre>{html.escape(text, quote=False)}</pre>"


def _tg_send(token, chat_id, text):
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat_id, "text": _mono(text),
                             "parse_mode": "HTML"})
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
            logger.warning(f"[panel] sendMessage {r.status_code}: {r.text[:200]}")
    except Exception:
        logger.exception("[panel] sendMessage failed")
    return None


def _tg_edit(token, chat_id, message_id, text):
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(f"https://api.telegram.org/bot{token}/editMessageText",
                       json={"chat_id": chat_id, "message_id": message_id,
                             "text": _mono(text), "parse_mode": "HTML"})
            # 400 "message is not modified" is benign; rate-limit 429 ignored.
            if r.status_code not in (200, 400, 429):
                logger.warning(f"[panel] editMessageText {r.status_code}: {r.text[:200]}")
    except Exception:
        logger.exception("[panel] editMessageText failed")


# --- Discord transport ---------------------------------------------------
# Same panel, rendered inside a ``` code block. The IdentityMap real_id
# for Discord may be either a channel id or a user id — the first send
# tries the id as a channel and falls back to opening a DM, then the
# resolved channel id is cached on the state for edits.


def _dc_block(text: str) -> str:
    return f"```\n{text}\n```"


def _dc_send(token, state, text):
    headers = {"Authorization": f"Bot {token}"}
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                f"https://discord.com/api/v10/channels/{state['chat_id']}/messages",
                headers=headers, json={"content": _dc_block(text)})
            if r.status_code != 200:
                dm = c.post("https://discord.com/api/v10/users/@me/channels",
                            headers=headers,
                            json={"recipient_id": state["chat_id"]})
                if dm.status_code != 200:
                    logger.warning(f"[panel] discord DM open {dm.status_code}")
                    return None
                state["chat_id"] = dm.json().get("id")
                r = c.post(
                    f"https://discord.com/api/v10/channels/{state['chat_id']}/messages",
                    headers=headers, json={"content": _dc_block(text)})
            if r.status_code == 200:
                return r.json().get("id")
            logger.warning(f"[panel] discord send {r.status_code}: {r.text[:200]}")
    except Exception:
        logger.exception("[panel] discord send failed")
    return None


def _dc_edit(token, state, text):
    try:
        with httpx.Client(timeout=10.0) as c:
            url = (f"https://discord.com/api/v10/channels/{state['chat_id']}"
                   f"/messages/{state['message_id']}")
            r = c.patch(url, headers={"Authorization": f"Bot {token}"},
                        json={"content": _dc_block(text)})
            if r.status_code not in (200, 429):
                logger.warning(f"[panel] discord edit {r.status_code}: {r.text[:200]}")
    except Exception:
        logger.exception("[panel] discord edit failed")


# --- Slack transport -------------------------------------------------------
# chat.postMessage returns the message `ts`, chat.update edits it. A U…
# user id is resolved to its D… DM channel once and cached on the state.


def _slack_block(text: str) -> str:
    return f"```\n{text}\n```"


def _slack_send(token, state, text):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=10.0) as c:
            chat = state["chat_id"]
            if chat and chat[0] not in ("C", "D", "G"):
                r = c.post("https://slack.com/api/conversations.open",
                           headers=headers, json={"users": chat})
                data = r.json()
                if not data.get("ok"):
                    logger.warning(f"[panel] slack DM open: {data.get('error')}")
                    return None
                state["chat_id"] = data["channel"]["id"]
            r = c.post("https://slack.com/api/chat.postMessage",
                       headers=headers,
                       json={"channel": state["chat_id"],
                             "text": _slack_block(text)})
            data = r.json()
            if data.get("ok"):
                return data.get("ts")
            logger.warning(f"[panel] slack send: {data.get('error')}")
    except Exception:
        logger.exception("[panel] slack send failed")
    return None


def _slack_edit(token, state, text):
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post("https://slack.com/api/chat.update",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"channel": state["chat_id"],
                             "ts": state["message_id"],
                             "text": _slack_block(text)})
            data = r.json()
            if not data.get("ok") and data.get("error") != "ratelimited":
                logger.warning(f"[panel] slack edit: {data.get('error')}")
    except Exception:
        logger.exception("[panel] slack edit failed")


_TRANSPORT_TOKEN_ENV = {
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
    "slack": "SLACK_BOT_TOKEN",
}


async def _flush(key: str):
    state = _PANELS.get(key)
    if not state:
        return
    transport = state.get("transport", "telegram")
    token = os.getenv(_TRANSPORT_TOKEN_ENV.get(transport, "TELEGRAM_BOT_TOKEN"))
    if not token or not state.get("chat_id"):
        return
    text = _render(state)
    if text == state.get("last_text"):
        return
    state["last_text"] = text
    if transport == "discord":
        if state.get("message_id") is None:
            state["message_id"] = await asyncio.to_thread(_dc_send, token, state, text)
        else:
            await asyncio.to_thread(_dc_edit, token, state, text)
    elif transport == "slack":
        if state.get("message_id") is None:
            state["message_id"] = await asyncio.to_thread(_slack_send, token, state, text)
        else:
            await asyncio.to_thread(_slack_edit, token, state, text)
    else:
        if state.get("message_id") is None:
            state["message_id"] = await asyncio.to_thread(
                _tg_send, token, state["chat_id"], text)
        else:
            await asyncio.to_thread(
                _tg_edit, token, state["chat_id"], state["message_id"], text)


def _has_doing(state) -> bool:
    return any(s[0] != _SEC and s[1] == "Doing" for s in state["steps"])


async def _ticker(key: str):
    """Animate breathing dots on every still-'Doing' line until none
    remain (then self-stop) or the task is cancelled on finalize."""
    try:
        while True:
            await asyncio.sleep(_TICK)
            lock = _LOCKS.get(key)
            if lock is None:
                return
            async with lock:
                state = _PANELS.get(key)
                if state is None:
                    return
                if not _has_doing(state):
                    state["ticker"] = None
                    return
                state["phase"] = state.get("phase", 0) + 1
                await _flush(key)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("[panel] ticker failed")


def _ensure_ticker(key: str, state: dict):
    if state.get("ticker") is None and _has_doing(state):
        try:
            state["ticker"] = asyncio.create_task(_ticker(key))
        except Exception:
            logger.exception("[panel] ticker start failed")


async def panel_step(key, recipient, channel, session_id, agent,
                     tool, phase, ok):
    """Record a tool step. phase='start' → '<tool> ... Doing';
    phase='end' → 'Done' (ok) / 'Failed'.

    Telegram / Discord / Slack: edit-in-place panel (rich UX).
    WebChat: fan out each transition as a separate /api/internal/push
    message (Phase A — no edit-in-place yet)."""
    if _is_webchat_channel(channel):
        try:
            from core.notifiers.webchat import send_webchat_notification
            status = ("done" if ok else "failed") if phase == "end" else "doing"
            # Blocking httpx push — offload so it can't freeze the event loop
            # (the TG/DC/Slack panel branches already go through to_thread).
            await asyncio.to_thread(
                send_webchat_notification,
                recipient, "",
                session_id=session_id, agent=agent,
                task_id=key, step=tool, status=status,
            )
        except Exception:
            logger.exception("[webchat-panel] step push failed")
        return
    transport = _panel_transport(channel)
    if transport is None:
        return
    if not key:
        return
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = _ensure_state(key, recipient, session_id, agent, transport)
        label = (tool or "tool").strip()
        # Match the most recent still-"Doing" line for this tool
        # (never a section divider).
        idx = None
        for i in range(len(state["steps"]) - 1, -1, -1):
            e = state["steps"][i]
            if e[0] == _SEC:
                continue
            if e[0] == label and e[1] == "Doing":
                idx = i
                break
        if phase == "start":
            if idx is None:
                state["steps"].append([label, "Doing"])
        else:
            new = "Done" if ok else "Failed"
            if idx is not None:
                state["steps"][idx][1] = new
            else:
                state["steps"].append([label, new])
        _trim(state)
        _ensure_ticker(key, state)
        await _flush(key)


async def panel_section(key, recipient, channel, session_id, agent, text):
    """Fold a sub-agent's send_message_now narration into the panel as a
    section divider; subsequent tool lines group under it.

    Telegram / Discord / Slack: panel section divider in the
    edit-in-place message.
    WebChat: forwarded as a one-off message (the section text IS the
    sub-agent's narration the user wants to read)."""
    if _is_webchat_channel(channel):
        try:
            from core.notifiers.webchat import send_webchat_notification
            # Blocking httpx push — offload so it can't freeze the event loop.
            await asyncio.to_thread(
                send_webchat_notification,
                recipient, text or "",
                session_id=session_id, agent=agent,
                task_id=key, step=None, status="section",
            )
        except Exception:
            logger.exception("[webchat-panel] section push failed")
        return
    transport = _panel_transport(channel)
    if transport is None:
        return
    t = _normalize_section(text)
    if not key or not (text or "").strip():
        return
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = _ensure_state(key, recipient, session_id, agent, transport)
        # Skip a consecutive duplicate section (agent repeats itself).
        for i in range(len(state["steps"]) - 1, -1, -1):
            if state["steps"][i][0] == _SEC:
                if state["steps"][i][1] == t:
                    return
                break
        state["steps"].append([_SEC, t])
        _trim(state)
        await _flush(key)


async def panel_finalize(key, status):
    """Flip the header to Done/Failed and do the final edit, then drop
    the panel state. status: 'done' | 'failed'."""
    if not key:
        return
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = _PANELS.get(key)
        if state is None:
            return
        t = state.get("ticker")
        if t is not None:
            t.cancel()
            state["ticker"] = None
        done = status == "done"
        state["header"] = "Done" if done else "Failed"
        for s in state["steps"]:
            if s[1] == "Doing":
                s[1] = "Done" if done else "Failed"
        await _flush(key)
        _PANELS.pop(key, None)
        _LOCKS.pop(key, None)
