"""Tests for the async ProjectTask synthetic-callback flow.

The contract under test:

  After execute_project_task() finishes successfully:
    - If task.session_id is set AND differs from the task-scoped session
      (i.e. it's the user's origin Manager session), the executor MUST inject
      a [SYSTEM_CALLBACK] turn into that session via run_adk_prompt and
      dispatch the Manager's reply to the user.
    - If task.session_id is not set, the executor MUST fall back to raw
      dispatch of the result text (legacy behaviour preserved).
    - If the synthetic call raises or returns a warning marker, the executor
      MUST fall back to raw dispatch — never swallow the result silently.

  After a task fails:
    - Same routing rules apply, but the synthetic message carries
      status=failed and a fallback text is sent if callback fails.
"""
import os
import uuid
import asyncio
from datetime import datetime
from unittest.mock import patch, AsyncMock

import pytest

from core import models
from mcp_servers.executors import project_task as executor_mod


def _make_task(db_session, *, session_id=None, status="queued"):
    epic = models.Epic(
        id=str(uuid.uuid4()),
        user_id="user_abc",
        title="Test Epic",
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(epic)
    task = models.ProjectTask(
        id=str(uuid.uuid4()),
        epic_id=epic.id,
        user_id="user_abc",
        session_id=session_id,
        title="Q1 Sales Analysis",
        spec="Do the analysis.",
        type="immediate",
        assigned_agent="business_analysis",
        status=status,
        channel="telegram",
        recipient="12345",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(task)
    db_session.commit()
    return task


@pytest.mark.asyncio
async def test_synthetic_callback_used_when_origin_session_present(db_session, monkeypatch):
    task = _make_task(db_session, session_id="tg_user_session_123")

    # Patch SessionLocal so executor uses our test DB
    monkeypatch.setattr(
        executor_mod, "SessionLocal", lambda: db_session
    )

    # Fake run_adk_prompt: first call (task session) returns raw result;
    # second call (origin session) returns Manager's natural reply.
    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append((app, uid, sid, prompt))
        if sid.startswith("task_"):
            return "Raw BA output: revenue +15% YoY"
        return "Manager natural reply about BA's findings"

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    # Drain background queue-advance tasks the executor spawns
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # Two run_adk_prompt calls: task session + origin (callback)
    assert len(run_calls) == 2
    assert run_calls[0][2].startswith("task_")
    assert run_calls[1][2] == "tg_user_session_123"
    # The second call must carry the SYSTEM_CALLBACK header
    assert "[SYSTEM_CALLBACK" in run_calls[1][3]
    assert "status=done" in run_calls[1][3]

    # Exactly one dispatch — and it carries Manager's reply, not raw output
    assert len(dispatch_calls) == 1
    _, _, body, sid = dispatch_calls[0]
    assert body == "Manager natural reply about BA's findings"
    assert sid == "tg_user_session_123"


@pytest.mark.asyncio
async def test_synthetic_callback_mentions_queued_downstream_and_forbids_asking(db_session, monkeypatch):
    """Regression for 2026-05-15: when Manager has already dispatched a
    downstream task (via Principle 0A — dispatch entire chain on OK), the
    callback synthetic prompt must tell Manager NOT to ask the user
    'should I continue?' because the chain is already in motion. Otherwise
    Manager turns a 2-minute auto-chain into a multi-prompt slog."""
    import uuid as _uuid
    task = _make_task(db_session, session_id="tg_origin_session_xyz")

    # Pre-create a downstream task that depends on `task`, as if the Manager
    # had already dispatched the whole chain on the user's OK.
    downstream = models.ProjectTask(
        id=str(_uuid.uuid4()),
        epic_id=task.epic_id,
        user_id=task.user_id,
        session_id=task.session_id,
        title="Generate PDF report",
        spec="Read upstream and produce PDF.",
        type="immediate",
        assigned_agent="business_analysis_agent",
        status="backlog",
        depends_on=task.id,
        channel="telegram",
        recipient="12345",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(downstream)
    db_session.commit()

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append((app, uid, sid, prompt))
        if sid.startswith("task_"):
            return "Raw upstream output"
        return "Manager natural reply"

    async def fake_dispatch(channel, recipient, body, sid):
        pass

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # The callback prompt (second call, on origin session) MUST mention the
    # downstream task and forbid asking the user.
    assert len(run_calls) == 2
    callback_prompt = run_calls[1][3]
    assert "Downstream task(s) already queued" in callback_prompt
    assert downstream.id[:8] in callback_prompt
    assert "business_analysis_agent" in callback_prompt
    assert "Do NOT ask" in callback_prompt
    assert "already dispatched" in callback_prompt


@pytest.mark.asyncio
async def test_synthetic_callback_allows_asking_when_no_downstream(db_session, monkeypatch):
    """Inverse of the above: when there's no queued downstream, the callback
    prompt should permit asking the user what's next."""
    task = _make_task(db_session, session_id="tg_origin_session_no_chain")

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append((app, uid, sid, prompt))
        if sid.startswith("task_"):
            return "Raw upstream output"
        return "Manager natural reply"

    async def fake_dispatch(channel, recipient, body, sid):
        pass

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    callback_prompt = run_calls[1][3]
    assert "No downstream task is queued" in callback_prompt
    assert "ask the user what they would like next" in callback_prompt


@pytest.mark.asyncio
async def test_falls_back_to_raw_dispatch_when_no_origin_session(db_session, monkeypatch):
    task = _make_task(db_session, session_id=None)

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    async def fake_run(app, uid, sid, prompt):
        return "Raw BA output"

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # No callback possible → single raw dispatch with the result text
    assert len(dispatch_calls) == 1
    _, _, body, _ = dispatch_calls[0]
    assert body == "Raw BA output"


@pytest.mark.asyncio
async def test_falls_back_when_callback_fails(db_session, monkeypatch):
    task = _make_task(db_session, session_id="tg_user_session_456")
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    async def fake_run(app, uid, sid, prompt):
        if sid.startswith("task_"):
            return "Raw result"
        raise RuntimeError("ADK unreachable for origin session")

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # Callback failed → executor MUST still deliver the raw result, not drop it
    assert len(dispatch_calls) == 1
    _, _, body, _ = dispatch_calls[0]
    assert body == "Raw result"


@pytest.mark.asyncio
async def test_falls_back_when_callback_returns_warning(db_session, monkeypatch):
    """run_adk_prompt returns '⚠️ Failed to get a response...' on exhaustion."""
    task = _make_task(db_session, session_id="tg_user_session_789")
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    async def fake_run(app, uid, sid, prompt):
        if sid.startswith("task_"):
            return "Raw result text"
        return "⚠️ Failed to get a response from the agent."

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # Warning marker treated as failure → fallback to raw
    assert len(dispatch_calls) == 1
    _, _, body, _ = dispatch_calls[0]
    assert body == "Raw result text"


@pytest.mark.asyncio
async def test_failure_path_uses_failure_callback(db_session, monkeypatch):
    task = _make_task(db_session, session_id="tg_user_session_fail")
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    async def fake_run(app, uid, sid, prompt):
        if sid.startswith("task_"):
            raise ValueError("BA blew up")
        # The failure-callback branch sees status=failed
        assert "status=failed" in prompt
        return "Manager's apology about the failed task"

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    assert len(dispatch_calls) == 1
    _, _, body, sid = dispatch_calls[0]
    assert body == "Manager's apology about the failed task"
    assert sid == "tg_user_session_fail"


@pytest.mark.asyncio
async def test_retry_exhausted_sentinel_marks_task_failed(db_session, monkeypatch):
    """Regression for GA audit: run_adk_prompt's retry-exhausted "⚠️ …"
    sentinel used to be stored as a `done` result — a model 404/429 outage
    was recorded as success and the user got the ⚠️ string as the
    deliverable. It must route through the failure path instead."""
    task = _make_task(db_session, session_id="tg_user_session_sentinel")
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    async def fake_run(app, uid, sid, prompt):
        if sid.startswith("task_"):
            return "⚠️ Failed to get a response from the agent."
        assert "status=failed" in prompt
        return "Manager explains the outage"

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    # The executor closes the session in its finally-block, detaching `task`
    # — re-query instead of refresh().
    row = db_session.query(models.ProjectTask).filter_by(id=task.id).one()
    assert row.status == "failed"
    # No `result` comment — only the issue comment from the failure path
    comments = (
        db_session.query(models.TaskComment)
        .filter(models.TaskComment.task_id == task.id)
        .all()
    )
    assert not [c for c in comments if c.type == "result"]
    assert [c for c in comments if c.type == "issue"]
    # The user hears about the failure, not a "⚠️ …" success message
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0][2] == "Manager explains the outage"


@pytest.mark.asyncio
async def test_failed_dependency_cascades_instead_of_spinning(db_session, monkeypatch):
    """Regression for GA audit: a downstream task whose upstream FAILED used
    to sit in 'queued' forever, re-fired by the 5s poll and early-returning
    each time — never failed, never reported. It must cascade to 'failed'
    and notify the user."""
    upstream_id = _make_task(db_session, status="failed").id
    downstream = _make_task(db_session, status="queued")
    downstream_id = downstream.id
    downstream.depends_on = upstream_id
    db_session.commit()

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)
    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append(sid)
        return "should never run"

    dispatch_calls = []

    async def fake_dispatch(channel, recipient, body, sid):
        dispatch_calls.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(downstream_id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, downstream_id).status == "failed"
    assert run_calls == []  # the agent must never be invoked
    # The user is told the chain broke
    assert len(dispatch_calls) == 1
    assert "failed" in dispatch_calls[0][2].lower()
    # An issue comment documents the upstream link
    issues = [
        c for c in db_session.query(models.TaskComment)
        .filter(models.TaskComment.task_id == downstream_id).all()
        if c.type == "issue"
    ]
    assert issues and upstream_id in issues[0].content


@pytest.mark.asyncio
async def test_agent_busy_defers_second_task(db_session, monkeypatch):
    """Per-agent serialization: while one task is 'doing', a second task for
    the SAME agent must stay 'queued' (poll re-fires it later) — concurrent
    MCP sessions on one sub-agent trigger the anyio cancel-scope race."""
    running = _make_task(db_session, status="doing")
    waiting = _make_task(db_session, status="queued")
    assert running.assigned_agent == waiting.assigned_agent

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)
    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append(sid)
        return "must not execute while agent is busy"

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)

    await executor_mod.execute_project_task(waiting.id)

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, waiting.id).status == "queued"
    assert run_calls == []


@pytest.mark.asyncio
async def test_license_block_cascades_to_downstream(db_session, monkeypatch):
    """Regression: a license-gate failure used to `return` without advancing
    the queue, stranding backlog dependents forever. It must now advance so
    downstream tasks cascade to failed like any other upstream failure."""
    upstream = _make_task(db_session, status="queued")
    upstream_id = upstream.id
    downstream = _make_task(db_session, status="backlog")
    downstream_id = downstream.id
    downstream.depends_on = upstream_id
    db_session.commit()

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        "mcp_servers.tools._shared.require_within_license",
        lambda db: "⛔ OSS usage limit reached — apply a license to continue.",
    )

    async def fake_dispatch(channel, recipient, body, sid):
        pass
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(upstream_id)
    # Let the queue-advance + cascaded downstream execute run
    for _ in range(10):
        await asyncio.sleep(0)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, upstream_id).status == "failed"
    # Downstream must not be left in backlog — it cascades to failed
    assert db_session.get(models.ProjectTask, downstream_id).status == "failed"


@pytest.mark.asyncio
async def test_agent_busy_defers_across_name_spellings(db_session, monkeypatch):
    """Regression: the busy-check compares NORMALIZED agent names. A task
    stored as 'coding' running must defer a second task stored as
    'coding_agent' — they are the same physical sub-agent, and letting both
    run concurrently is exactly the anyio cancel-scope race the
    serialization is meant to prevent."""
    running = _make_task(db_session, status="doing")
    running.assigned_agent = "coding"
    waiting = _make_task(db_session, status="queued")
    waiting.assigned_agent = "coding_agent"  # same agent, different spelling
    db_session.commit()
    waiting_id = waiting.id

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)
    run_calls = []

    async def fake_run(app, uid, sid, prompt):
        run_calls.append(sid)
        return "must not run — agent busy under a different spelling"

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)

    await executor_mod.execute_project_task(waiting_id)

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, waiting_id).status == "queued"
    assert run_calls == []
