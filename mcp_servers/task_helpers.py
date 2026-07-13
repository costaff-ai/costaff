"""Helpers for project task execution.

These helpers are tightly coupled to the MCP scheduler executors
(`mcp_servers/executors/*.py`) and work with project ORM models
(Epic, Story, ProjectTask, IdentityMap). They live alongside the
executors rather than in the cross-cutting `core/` layer.
"""
import os

from core import models


def normalize_agent_name(name: str) -> str:
    """Collapse the many spellings the Manager LLM uses for one agent.

    The Manager passes any of "coding" / "coding_agent" /
    "costaff-agent-coding" / "business_analysis_agent", and the form stored
    on a task at create-time may differ from the form a later call uses.
    Every per-agent identity comparison (serialization busy-check, queue
    advance, poll) MUST go through this — a raw `==` lets two spellings of
    the SAME physical agent run concurrently, defeating the one-task-per-
    agent guarantee that keeps concurrent MCP sessions (→ the anyio
    cancel-scope race) from happening.
    """
    n = (name or "").replace("-", "_")
    if n.startswith("costaff_agent_"):
        n = n[len("costaff_agent_"):]
    if n.endswith("_agent"):
        n = n[:-len("_agent")]
    return n


def get_user_channel_info(user_id: str, db, allow_env_fallback: bool = True) -> tuple:
    """Look up the user's primary notification channel from IdentityMap.

    Returns (channel, hashed_id) or (None, None) if no mapping exists.
    The channel is inferred from the session_id prefix:
        tg_*               → telegram
        dc_* / discord_*   → discord  (adapter prefix is "discord"; "dc" is legacy)
        slack_*            → slack
        line_*             → line
        web_*              → webchat  (legacy OSS WebChat)
        webent_*           → webchat  (WebChat Enterprise — same notifier path)
    The recipient is always the hashed_id so dispatch_notification can
    resolve it back to a real platform id.

    `allow_env_fallback` (default True) controls the WebChat-Enterprise
    fallback GUESS returned when there is no local IdentityMap (or an unknown
    prefix): fine for FILLING a missing channel, but callers deciding whether
    to OVERRIDE an explicitly-set channel must pass False — otherwise the
    guess overrides a correct, explicit channel (e.g. a federation node that
    also runs Telegram would misroute a Telegram task to WebChat).
    """
    mapping = (
        db.query(models.IdentityMap)
        .filter(models.IdentityMap.hashed_id == user_id)
        .order_by(models.IdentityMap.created_at.desc())
        .first()
    )
    if not mapping:
        # No local identity. On a remote CoStaff machine in the WebChat-
        # Enterprise federation the user's identity lives in the UI host's
        # enterprise DB, not in THIS machine's identity_maps — so the lookup
        # finds nothing and async progress / project-task results would
        # default to telegram and never reach the user. If this machine is
        # wired to push to an enterprise WebChat (WEBCHAT_ENT_PUSH_URL set),
        # treat the user as a WebChat user: the push lands on the enterprise
        # container, which resolves the hashed_id against ITS own IdentityMap
        # and delivers to the right conversation.
        if allow_env_fallback and os.getenv("WEBCHAT_ENT_PUSH_URL"):
            return "webchat", user_id
        return None, None
    sid = mapping.session_id or ""
    if sid.startswith("tg_"):
        return "telegram", user_id
    if sid.startswith(("dc_", "discord_")):
        return "discord", user_id
    if sid.startswith("slack_"):
        return "slack", user_id
    if sid.startswith("line_"):
        return "line", user_id
    # Both `web_` (OSS) and `webent_` (Enterprise) route through the
    # WebChat notifier — they share the HTTP push protocol over the
    # docker network.
    if sid.startswith("webent_") or sid.startswith("web_"):
        return "webchat", user_id
    # Unknown prefix: same enterprise-federation fallback as no-mapping above.
    if allow_env_fallback and os.getenv("WEBCHAT_ENT_PUSH_URL"):
        return "webchat", user_id
    return None, None


def build_task_spec(task, db) -> str:
    """Build a context-enriched execution spec for costaff_agent.

    Prepends Epic and Story titles, delegation instructions when the task
    targets an external agent, and a PROGRESS_CONTEXT block so the
    executing agent can stream live updates back to the user's channel.
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
            f"\n[EXECUTION CONTEXT — YOU ARE NOT THE MANAGER RIGHT NOW]\n"
            f"This message reached you inside an asynchronous executor session "
            f"(session_id starts with `task_`), NOT inside the user's chat. "
            f"You are running as the SPECIALIST EXECUTOR for this single task.\n"
            f"\n"
            f"⛔ ABSOLUTELY FORBIDDEN in this session:\n"
            f"  - `dispatch_task(...)` — you are not planning a chain, you are executing one step\n"
            f"  - `create_project_task(...)` / `update_task_queue(...)` — same reason\n"
            f"  - `create_epic(...)` / `create_story(...)` — planning belongs in the user-facing turn\n"
            f"Calling any of the above causes a recursive task explosion. Reproduced 2026-05-15:\n"
            f"a single user request produced 4 Coding tasks because the executor session\n"
            f"kept calling dispatch_task again instead of delegating to coding_agent directly.\n"
            f"\n"
            f"✅ What you MUST do in this session:\n"
            f"1. Call add_task_comment(task_id=\"{task.id}\", comment_type=\"note\") with an implementation plan BEFORE delegating.\n"
            f"   Format the plan as:\n"
            f"   ## Implementation Plan\n"
            f"   - **Goal**: <what this task needs to achieve>\n"
            f"   - **Steps**:\n"
            f"     1. <step>\n"
            f"   - **Expected Output**: <files, tables, reports, etc.>\n"
            f"2. Call the {task.assigned_agent} AgentTool directly — i.e. `{task.assigned_agent}(request=\"...\")` — passing the FULL task spec above (including PROGRESS_CONTEXT).\n"
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

        lines.append(
            f"\n(System: Autonomous project task ID={task.id}. Execute it. Respond in {preferred_lang}.)"
        )

    # Resolve channel/recipient for PROGRESS_CONTEXT so the executing agent
    # can stream live updates back to the user. The Manager often sets
    # channel + session_id but NOT recipient; the old `if not channel:`
    # only filled when channel was ALSO empty, so a channel-set/
    # recipient-empty task left recipient None → the `if channel and
    # recipient:` guard below skipped the PROGRESS_CONTEXT block entirely
    # and the sub-agent stayed silent for the whole run. Resolve whichever
    # field is missing, independently (mirrors execute_project_task).
    channel = task.channel
    recipient = task.recipient
    if not channel or not recipient:
        ch2, rc2 = get_user_channel_info(task.user_id, db)
        channel = channel or ch2
        recipient = recipient or rc2

    # Normalise channel against the user's IdentityMap. Manager LLM has
    # been observed (2026-05-26) hardcoding channel='telegram' for users
    # whose session_id is webent_* — that routes progress to the wrong
    # notifier and the user sees nothing. The IdentityMap is the only
    # ground truth for which surface the user is currently on.
    actual_channel, _ = get_user_channel_info(task.user_id, db)
    if actual_channel and channel and actual_channel != channel:
        channel = actual_channel

    if channel and recipient:
        # The session_id we expose to the sub-agent is the DELIVERY target,
        # not the sub-agent's own ADK session (which is `task_<id>` and set
        # by execute_project_task at run time). Using `task.session_id` —
        # the user's session captured when the task was created — ensures
        # progress lands in the right surface:
        #   • Telegram: `tg_<chatid>` ⇒ Telegram notifier uses it directly
        #   • WebChat Enterprise (post-thread refactor): `webent_<hash>` is
        #     thread-scoped because real_id includes conversation_id, so
        #     progress reaches the same thread the task was launched from
        # PROGRESS_CONTEXT.session_id is the **panel key** — it must be
        # UNIQUE PER TASK so concurrent tasks for the same user don't
        # merge into one panel. We always use `task_<task_id>` here;
        # what Manager LLM passed in `task.session_id` may or may not be
        # a real session id, but it's never per-task-unique.
        #
        # Delivery routing is a separate concern handled downstream by
        # the channel notifier: `core/notifiers/webchat.py` falls back
        # to IdentityMap lookup by recipient (PROGRESS_CONTEXT.user_id /
        # hashed_id) whenever session_id doesn't have a known channel
        # prefix — see `_resolve_session_id`. So `task_<id>` arrives at
        # the WebChat backend, gets matched via IdentityMap, and lands
        # in the right user's chat surface.
        #
        # The sub-agent's `progress.py` before_model_callback also
        # explicitly requires `session_id.startswith("task_")` to arm
        # the panel — anything else and the callback returns silently,
        # so no tool steps get reported.
        deliver_session = f"task_{task.id}"
        lines.append(
            f"\n[PROGRESS_CONTEXT]\n"
            f"user_id={task.user_id}\n"
            f"channel={channel}\n"
            f"session_id={deliver_session}"
        )

    return "\n".join(lines)
