"""Deterministic PROGRESS_CONTEXT forwarding into sub-agent AgentTool calls.

The executor feeds the Manager a spec that build_task_spec() already
enriched with a [PROGRESS_CONTEXT] block. The Manager LLM is *instructed*
to copy that block into the `business_analysis_agent(request="...")`
call, but it drops it unreliably — so the A2A sub-agent never sees the
task's real session_id/channel and cannot drive a live panel.

This before_tool_callback removes the LLM from that hop: for any
AgentTool call (anything with a string `request` arg), if the Manager's
own input carried a [PROGRESS_CONTEXT] block and the outgoing request
does not already contain one, append it verbatim. Pure text, no DB, no
network — runs in the Manager (a normal local agent whose session IS the
executor's `task_<id>` session), so it is fully deterministic.

Fail-safe: never raises, returns None (must not skip the tool call).
"""
import logging
import re

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(
    r"\[PROGRESS_CONTEXT\]\n"
    r"user_id=[^\n]*\n"
    r"channel=[^\n]*\n"
    r"session_id=task_[^\n]*"
)


def _content_text(content) -> str:
    try:
        parts = getattr(content, "parts", None) or []
        return "\n".join((getattr(p, "text", "") or "") for p in parts)
    except Exception:
        return ""


# Task-creation/dispatch tools whose `session_id` arg is the DELIVERY target
# for async progress + result. The Manager LLM fills this unreliably (observed
# 2026-06-01: it passed the user hashed_id instead of the conversation's
# adk_session_id, so WebChat Enterprise couldn't match it to the originating
# conversation and progress leaked into whatever thread the user last opened).
# The real session is on the ADK tool_context — override deterministically.
_SESSION_OVERRIDE_TOOLS = {
    "create_project_task",
    "dispatch_task",
    "dispatch_plan",          # multi-step plan dispatch — the real path the
                              # Manager uses for "查X並出PDF" (observed 2026-06-01);
                              # was missing → session_id stayed the user hash.
    "update_task_queue",
    "create_project_with_tasks",
    "create_reminder_tool",
    "create_regular_work",
}


def _current_session_id(tool_context) -> str | None:
    try:
        sess = getattr(tool_context, "session", None)
        return getattr(sess, "id", None)
    except Exception:
        return None


async def before_tool_callback(tool, args, tool_context):
    # --- Deterministic session_id pinning for task/delivery tools ---
    # Runs BEFORE the PROGRESS_CONTEXT block below and is independent of it.
    try:
        tool_name = getattr(tool, "name", "")
        if isinstance(args, dict) and tool_name in _SESSION_OVERRIDE_TOOLS:
            sid = _current_session_id(tool_context)
            if sid and args.get("session_id") != sid:
                prev = args.get("session_id")
                args["session_id"] = sid
                logger.info(
                    "[session-pin] %s session_id %r -> %r (ADK tool_context)",
                    tool_name, prev, sid,
                )
    except Exception:
        logger.info("[session-pin] failed", exc_info=True)

    # --- act-as identity injection (identity propagation) ---
    # Source the verified identity from the Manager's OWN session state (seeded
    # by the UI host at session create — trusted, server-side, NOT the LLM and
    # NOT from user message text). Strip any [ACT_AS_IDENTITY] the LLM may have
    # copied from forged user text, then append the trusted block for the HRM
    # AgentTool. The agent binds it to state; its McpToolset header_provider
    # turns it into X-Act-As-Email so the HRM backend enforces real RBAC.
    try:
        tool_name = getattr(tool, "name", "") or ""
        if isinstance(args, dict) and isinstance(args.get("request"), str) \
                and "hrm" in tool_name.lower():
            req2 = re.sub(r"\n*\[ACT_AS_IDENTITY\][^\[]*", "", args["request"])
            st = getattr(tool_context, "state", None)
            ident = (st.get("costaff_identity") if st else None) or {}
            email = (ident.get("email") or "").strip() if isinstance(ident, dict) else ""
            if email:
                req2 = req2.rstrip() + "\n\n[ACT_AS_IDENTITY]\nemail=" + email
                logger.info("[act-as] injected identity into %s request", tool_name)
            args["request"] = req2
    except Exception:
        logger.info("[act-as] inject failed", exc_info=True)

    try:
        if not isinstance(args, dict):
            return None
        req = args.get("request")
        if not isinstance(req, str):
            return None
        if "[PROGRESS_CONTEXT]" in req:
            return None

        src = _content_text(getattr(tool_context, "user_content", None))
        m = _BLOCK_RE.search(src)
        if not m:
            return None

        args["request"] = req.rstrip() + "\n\n" + m.group(0)
        logger.info(
            "[pc-inject] appended PROGRESS_CONTEXT to %s request",
            getattr(tool, "name", "?"),
        )
    except Exception:
        logger.info("[pc-inject] failed", exc_info=True)
    return None
