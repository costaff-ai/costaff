import os
import re
import asyncio
import uuid
from datetime import datetime

from core import models
from core.database import SessionLocal
from core.adk_client import run_adk_prompt
from core.license import LicenseManager
from mcp_servers.setup import logger
from core.notifiers.dispatcher import dispatch_notification
from core.notifiers.result_envelope import parse_result_envelope
from mcp_servers.task_helpers import get_user_channel_info, build_task_spec


class OutputVerificationError(Exception):
    """Raised when a sub-agent's RESULT claims output files that are not on disk."""


# Paths the sub-agent claims it wrote, as they appear in its RESULT block.
# Must match the same shape `core/notifiers/telegram.extract_file_paths` looks
# for, so the verifier and the notifier agree on what counts as a "declared
# output". The notifier filters to existing-only and silently drops missing
# paths; this verifier deliberately does NOT filter — its job is to surface
# the missing ones BEFORE the executor declares the task done.
_OUTPUT_FILE_EXTS = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"
_DECLARED_PATH_RE = re.compile(
    r"(/app/data/[\w./-]+\.(?:" + _OUTPUT_FILE_EXTS + r"))",
    re.IGNORECASE,
)


def _agent_slot(agent_name: str | None) -> str | None:
    """Convert an assigned_agent name to its shared-volume slot directory.

    Examples:
      coding                 → costaff-agent-coding
      business_analysis      → costaff-agent-business-analysis
      twinkle_hub_agent      → costaff-agent-twinkle-hub
      costaff_agent          → None   (manager itself has no agent slot)
    """
    if not agent_name:
        return None
    n = agent_name.replace("-", "_")
    if n.startswith("costaff_agent_"):
        n = n[len("costaff_agent_"):]
    if n.endswith("_agent"):
        n = n[: -len("_agent")]
    if not n or n == "costaff":
        return None
    return "costaff-agent-" + n.replace("_", "-")


def _verify_declared_outputs(result_text: str, agent_name: str | None = None) -> list[str]:
    """Return any output file paths in the sub-agent's RESULT that don't exist
    on disk — **scoped to this agent's own shared slot only**.

    Two-stage extraction (mirrors the notifier's extract_file_paths):
    1. If the agent emitted a structured envelope with an explicit `files:`
       list, verify each file in that list (filtered to this agent's slot).
    2. Otherwise, fall back to regex over the raw text. Both stages then
       scope to `/app/data/shared/<this-agent-slot>/` so the verifier only
       flags THIS agent's claimed deliverables, never upstream inputs.

    A sub-agent's RESULT block often references files from other agents (BA
    reads Coding's CSV; Coding reads Twinkle's JSON). Those upstream paths
    are not THIS agent's deliverables; they're inputs, and verifying them
    here would race against the upstream task's writes when the Manager
    dispatches steps in parallel.

    Returns:
      - [] when no in-slot paths are mentioned (task may have produced no files)
      - [] when every in-slot path exists on disk
      - list of missing in-slot paths otherwise
    """
    if not result_text:
        return []
    slot = _agent_slot(agent_name)
    if not slot:
        # No slot to scope to → skip verification rather than over-flag.
        return []
    needle = f"/app/data/shared/{slot}/"
    seen: set[str] = set()
    missing: list[str] = []

    # Stage 1: structured envelope (preferred — exact list of claimed files)
    envelope = parse_result_envelope(result_text)
    if envelope.structured and envelope.files:
        for p in envelope.files:
            if needle not in p:
                continue
            if p in seen:
                continue
            seen.add(p)
            if not os.path.isfile(p):
                missing.append(p)
        return missing

    # Stage 2: legacy regex over free-text RESULT
    for p in _DECLARED_PATH_RE.findall(result_text):
        if needle not in p:
            continue
        if p in seen:
            continue
        seen.add(p)
        if not os.path.isfile(p):
            missing.append(p)
    return missing


async def execute_project_task(task_id: str):
    """Execute a ProjectTask by calling costaff_agent with full project context."""
    db = SessionLocal()
    try:
        task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()
        if not task or task.status in ("doing",):
            return

        # Check dependency
        if task.depends_on:
            dep = db.query(models.ProjectTask).filter(models.ProjectTask.id == task.depends_on).first()
            if dep and dep.status not in ("done",):
                logger.info(f"ProjectTask {task_id} waiting on dependency {task.depends_on}")
                return

        logger.info(f"Executing ProjectTask {task_id}: {task.title}")

        # Resolve channel/recipient — auto-detect from IdentityMap if not set
        # on the task. The Manager frequently sets channel + session_id but
        # NOT recipient; the old `if not channel:` only filled when channel
        # was ALSO empty, so a channel-set/recipient-empty task left recipient
        # None → the `if channel and recipient:` delivery guard below silently
        # skipped ALL progress / result / file delivery (user saw nothing in
        # Telegram). Resolve whichever field is missing, independently.
        channel = task.channel
        recipient = task.recipient
        if not channel or not recipient:
            ch2, rc2 = get_user_channel_info(task.user_id, db)
            channel = channel or ch2
            recipient = recipient or rc2

        # License gate (decisions A+B+C): if the license is degraded to OSS
        # and usage exceeds OSS limits, refuse to execute. Fail the task with
        # a clear message and notify the user instead of silently stalling.
        from mcp_servers.tools._shared import require_within_license
        license_block = require_within_license(db)
        if license_block:
            task.status = "failed"
            task.updated_at = datetime.utcnow()
            db.add(models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task_id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=license_block,
                type="result",
                created_at=datetime.utcnow(),
            ))
            db.commit()
            if channel and recipient:
                try:
                    await dispatch_notification(
                        channel, recipient, license_block, task.session_id
                    )
                except Exception:
                    logger.exception(
                        "[execute_project_task] failed to notify license "
                        "block for task %s", task_id
                    )
            logger.warning(
                "[execute_project_task] task %s blocked by license gate",
                task_id,
            )
            return

        task.status = "doing"
        task.updated_at = datetime.utcnow()
        db.commit()

        # Write start comment
        start_comment = models.TaskComment(
            id=str(uuid.uuid4()),
            task_id=task_id,
            user_id=task.user_id,
            author=task.assigned_agent or "costaff_agent",
            content=(
                f"## 🚀 Started\n"
                f"- **Task**: {task.title}\n"
                f"- **Assigned Agent**: {task.assigned_agent or 'costaff_agent'}\n"
                f"- **Description**: {(task.spec or '').strip()[:300] or '—'}"
            ),
            type="note",
            created_at=datetime.utcnow()
        )
        db.add(start_comment)
        db.commit()

        # Build context-enriched spec and use task-scoped session to prevent context bleed
        spec = build_task_spec(task, db)
        task_session_id = f"task_{task_id}"
        app_name = os.getenv("ADK_APP_NAME", "costaff_agent")

        try:
            result_text = await run_adk_prompt(app_name, task.user_id, task_session_id, spec)

            # Declared-output verification — DISABLED by default.
            # It repeatedly false-failed successful BA/Coding tasks (a file
            # the sub-agent just wrote lags becoming visible to THIS executor
            # container: write flush + cross-container bind-mount visibility)
            # and became a pipeline bottleneck. We now only LOG the signal
            # and let the task proceed. Set COSTAFF_VERIFY_DECLARED_OUTPUTS=1
            # to restore hard failure (with the ~10s grace retry) once the
            # underlying visibility lag is properly addressed.
            _verify_enabled = os.getenv(
                "COSTAFF_VERIFY_DECLARED_OUTPUTS", "0"
            ).strip().lower() in ("1", "true", "yes")
            missing_outputs = _verify_declared_outputs(result_text, task.assigned_agent)
            if missing_outputs and _verify_enabled:
                for _attempt in range(5):  # up to ~10s grace
                    await asyncio.sleep(2)
                    missing_outputs = _verify_declared_outputs(
                        result_text, task.assigned_agent
                    )
                    if not missing_outputs:
                        logger.info(
                            f"[execute_project_task] task {task_id} declared "
                            f"outputs became visible after grace retry "
                            f"(attempt {_attempt + 1})"
                        )
                        break
            if missing_outputs:
                if _verify_enabled:
                    logger.error(
                        f"[execute_project_task] task {task_id} declared outputs "
                        f"that do not exist on disk after grace retries: {missing_outputs}"
                    )
                    raise OutputVerificationError(
                        "Sub-agent declared output files that are not on disk: "
                        + ", ".join(missing_outputs)
                    )
                logger.warning(
                    f"[execute_project_task] task {task_id} declared outputs not "
                    f"visible to executor (verification disabled, task NOT "
                    f"failed): {missing_outputs}"
                )

            task.status = "done"
            task.last_run = datetime.utcnow()
            task.updated_at = datetime.utcnow()

            comment = models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task_id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=result_text,
                type="result",
                created_at=datetime.utcnow()
            )
            db.add(comment)
            db.commit()

            # Flip the live progress panel header → Done (fail-safe).
            try:
                from core.notifiers.progress_panel import panel_finalize
                await panel_finalize(f"task_{task_id}", "done")
            except Exception:
                logger.exception("[execute_project_task] panel finalize(done) swallowed")

            if channel and recipient:
                # If the task carries an origin session_id (the user's main
                # conversation), inject a SYSTEM_CALLBACK turn into that session
                # so the Manager re-engages and presents the result naturally
                # in the user's conversation thread. Falls back to raw dispatch
                # if the synthetic callback fails (e.g. session expired, ADK
                # unreachable).
                origin_session_id = task.session_id
                callback_delivered = False
                if origin_session_id and origin_session_id != task_session_id:
                    # Detect whether the Manager has already dispatched a
                    # downstream task that depends on this one. If yes, the
                    # callback prompt must tell Manager to summarise + report
                    # progress (NOT ask the user "should I continue?"), because
                    # the chain is already in motion. Querying here keeps the
                    # synthetic prompt accurate at callback time.
                    dependents = (
                        db.query(models.ProjectTask)
                        .filter(
                            models.ProjectTask.depends_on == task_id,
                            models.ProjectTask.status.in_(["backlog", "queued", "doing"]),
                        )
                        .order_by(models.ProjectTask.created_at.asc())
                        .all()
                    )
                    if dependents:
                        next_steps_note = (
                            "\n\nDownstream task(s) already queued for this chain:\n"
                            + "\n".join(
                                f"  - #{d.id[:8]} → {d.assigned_agent}: {d.title}"
                                for d in dependents
                            )
                            + "\n\nThe chain is already in motion. Summarise THIS task's "
                            "result and tell the user the next step is now running. "
                            "Do NOT ask 'should I continue?' or 'do you want me to "
                            "dispatch the next agent?' — that step is already dispatched. "
                            "Do NOT call dispatch_task or create_project_task again."
                        )
                    else:
                        next_steps_note = (
                            "\n\nNo downstream task is queued. Summarise the result and "
                            "ask the user what they would like next, if anything. "
                            "Do NOT call dispatch_task or create_project_task unless the "
                            "user explicitly asks for follow-up work."
                        )
                    try:
                        synthetic = (
                            f"[SYSTEM_CALLBACK|task_id={task_id}"
                            f"|agent={task.assigned_agent or 'costaff_agent'}"
                            f"|status=done]\n"
                            f"Original task title: {task.title}\n"
                            f"Result from sub-agent:\n{result_text[:4000]}\n"
                            f"\nInstructions: this is an asynchronous task the user "
                            f"asked about earlier. Summarise the result in the user's "
                            f"language using your usual style."
                            f"{next_steps_note}"
                        )
                        manager_reply = await run_adk_prompt(
                            app_name, task.user_id, origin_session_id, synthetic
                        )
                        if manager_reply and not manager_reply.startswith("⚠️"):
                            await dispatch_notification(
                                channel, recipient, manager_reply, origin_session_id
                            )
                            callback_delivered = True
                            logger.info(
                                f"[execute_project_task] synthetic callback "
                                f"delivered for task {task_id} → session "
                                f"{origin_session_id}"
                            )
                    except Exception:
                        logger.exception(
                            f"[execute_project_task] synthetic callback failed "
                            f"for task {task_id}, falling back to raw dispatch"
                        )

                if not callback_delivered:
                    await dispatch_notification(
                        channel, recipient, result_text, task_session_id
                    )

            # Advance queue and wake up dependents
            if task.assigned_agent:
                asyncio.create_task(_advance_agent_queue(task.assigned_agent, task.user_id, finished_task_id=task_id))

        except Exception as e:
            logger.error(f"ProjectTask execution failed {task_id}: {e}")
            task.status = "failed"
            task.updated_at = datetime.utcnow()
            try:
                from core.notifiers.progress_panel import panel_finalize
                await panel_finalize(f"task_{task_id}", "failed")
            except Exception:
                logger.exception("[execute_project_task] panel finalize(failed) swallowed")
            import traceback
            comment = models.TaskComment(
                id=str(uuid.uuid4()),
                task_id=task_id,
                user_id=task.user_id,
                author=task.assigned_agent or "costaff_agent",
                content=(
                    f"## ❌ Error Occurred\n"
                    f"- **Error Type**: {type(e).__name__}\n"
                    f"- **Error Message**: {str(e)}\n"
                    f"- **Location**: Agent execution stage (task_id={task_id})\n"
                    f"- **Traceback**:\n```\n{traceback.format_exc()[-1000:]}\n```"
                ),
                type="issue",
                created_at=datetime.utcnow()
            )
            db.add(comment)
            db.commit()

            # Notify the user about the failure — via synthetic callback if we
            # have an origin session, otherwise raw dispatch.
            if channel and recipient:
                origin_session_id = task.session_id
                failure_delivered = False
                if origin_session_id and origin_session_id != task_session_id:
                    try:
                        synthetic = (
                            f"[SYSTEM_CALLBACK|task_id={task_id}"
                            f"|agent={task.assigned_agent or 'costaff_agent'}"
                            f"|status=failed]\n"
                            f"Original task title: {task.title}\n"
                            f"Error type: {type(e).__name__}\n"
                            f"Error message: {str(e)[:500]}\n"
                            f"\nInstructions: this async task failed. Tell the user "
                            f"in their language what failed and suggest a recovery "
                            f"action (retry, change approach, or skip)."
                        )
                        manager_reply = await run_adk_prompt(
                            app_name, task.user_id, origin_session_id, synthetic
                        )
                        if manager_reply and not manager_reply.startswith("⚠️"):
                            await dispatch_notification(
                                channel, recipient, manager_reply, origin_session_id
                            )
                            failure_delivered = True
                    except Exception:
                        logger.exception(
                            f"[execute_project_task] failure callback errored "
                            f"for task {task_id}"
                        )
                if not failure_delivered:
                    fallback = (
                        f"❌ Task '{task.title}' (id={task_id}) failed: "
                        f"{type(e).__name__}: {str(e)[:300]}"
                    )
                    await dispatch_notification(
                        channel, recipient, fallback, task_session_id
                    )

            # Still advance the queue even on failure so remaining tasks are not blocked
            if task.assigned_agent:
                asyncio.create_task(_advance_agent_queue(task.assigned_agent, task.user_id, finished_task_id=task_id))


    finally:
        db.close()


async def _advance_agent_queue(agent_id: str, user_id: str, finished_task_id: str = None):
    """
    1. Pick up the next already-queued task for this specific agent.
    2. [NEW] Wake up any dependent tasks (from ANY agent) that were waiting for this finished task.
    """
    db = SessionLocal()
    try:
        # 1. Trigger dependent tasks across the whole project
        if finished_task_id:
            dependents = (
                db.query(models.ProjectTask)
                .filter(models.ProjectTask.depends_on == finished_task_id)
                .all()
            )
            for dep_task in dependents:
                if dep_task.status == "backlog":
                    logger.info(f"Dependency met! Queuing dependent task: {dep_task.id} (Agent: {dep_task.assigned_agent})")
                    dep_task.status = "queued"
                    dep_task.updated_at = datetime.utcnow()
                    db.commit() # Commit each change immediately to avoid race
                    asyncio.create_task(execute_project_task(dep_task.id))

        # 2. Advance the original agent's own queue (existing logic)
        next_task = (
            db.query(models.ProjectTask)
            .filter(
                models.ProjectTask.assigned_agent == agent_id,
                models.ProjectTask.user_id == user_id,
                models.ProjectTask.status == "queued"
            )
            .order_by(models.ProjectTask.queue_order.asc().nullslast(), models.ProjectTask.created_at.asc())
            .first()
        )
        if next_task:
            logger.info(f"Advancing queue: next task for {agent_id} is {next_task.id}")
            asyncio.create_task(execute_project_task(next_task.id))
    finally:
        db.close()
