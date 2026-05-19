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
    # Collapse consecutive identical tool lines into one "× N" line
    # (purely visual — state stays full so step matching is unaffected).
    i = 0
    n = len(steps)
    while i < n:
        label, st = steps[i]
        if label == _SEC:
            lines.append(f"- {st}")
            i += 1
            continue
        j = i + 1
        while j < n and steps[j][0] == label and steps[j][1] == st:
            j += 1
        run = j - i
        suffix = f" ×{run}" if run > 1 else ""
        lines.append(f"  {label} - {st}{suffix}")
        i = j
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


def _ensure_state(key, recipient, session_id, agent) -> dict:
    state = _PANELS.get(key)
    if state is None:
        state = {
            "chat_id": _resolve_chat(recipient, session_id),
            "message_id": None, "steps": [],
            "agent_disp": _display_agent(agent),
            "task_title": _resolve_task_title(key),
            "header": "Working", "last_text": None,
            "phase": 0, "ticker": None,
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


async def _flush(key: str):
    state = _PANELS.get(key)
    if not state:
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not state.get("chat_id"):
        return
    text = _render(state)
    if text == state.get("last_text"):
        return
    state["last_text"] = text
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
    phase='end' → 'Done' (ok) / 'Failed'. Telegram only (MVP)."""
    if (channel or "").lower() not in ("telegram", "tg"):
        return
    if not key:
        return
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = _ensure_state(key, recipient, session_id, agent)
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
    section divider; subsequent tool lines group under it. Telegram only."""
    if (channel or "").lower() not in ("telegram", "tg"):
        return
    t = _normalize_section(text)
    if not key or not (text or "").strip():
        return
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = _ensure_state(key, recipient, session_id, agent)
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
