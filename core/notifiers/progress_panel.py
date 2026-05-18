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
import logging
import os

import httpx

from core import models
from core.database import SessionLocal

logger = logging.getLogger("costaff-agent-engine")

# Breathing-dots tick interval (s). ~1.3s keeps it lively without
# tripping Telegram's edit rate limit (429 is handled benignly anyway).
_TICK = float(os.getenv("COSTAFF_PANEL_TICK", "1.3"))

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


def _render(state: dict) -> str:
    lines = [f"[ {state['agent_disp']} ] {state['header']}"]
    dots = "." * (1 + state.get("phase", 0) % 3)
    for label, st in state["steps"]:
        shown = f"Doing{dots}" if st == "Doing" else st
        lines.append(f"{label} - {shown}")
    return "\n".join(lines)


def _tg_send(token, chat_id, text):
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat_id, "text": text})
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
                             "text": text})
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
    return any(s[1] == "Doing" for s in state["steps"])


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
        state = _PANELS.get(key)
        if state is None:
            state = {
                "chat_id": _resolve_chat(recipient, session_id),
                "message_id": None, "steps": [],
                "agent_disp": _display_agent(agent),
                "header": "Working", "last_text": None,
                "phase": 0, "ticker": None,
            }
            _PANELS[key] = state
        label = (tool or "tool").strip()
        # Match the most recent still-"Doing" line for this tool.
        idx = None
        for i in range(len(state["steps"]) - 1, -1, -1):
            if state["steps"][i][0] == label and state["steps"][i][1] == "Doing":
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
        _ensure_ticker(key, state)
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
