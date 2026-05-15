"""Tests for the atomic `dispatch_task` MCP tool.

`dispatch_task` is the canonical create+queue primitive that replaces the
legacy two-step flow (`create_project_task` → `update_task_queue`). The
contract under test:

  - Inserts a row with status='queued' (NOT 'backlog') in one atomic call.
  - Appends to the agent's queue (queue_order = max + 1).
  - For type='immediate' (no cron), triggers execute_project_task right away.
  - For type='scheduled' (cron set), does NOT trigger the executor.
  - assigned_agent is required.
  - The user must be approved (require_approved gate).
"""
import uuid
import asyncio
from datetime import datetime

import pytest

from core import models
from mcp_servers.tools import project_tasks as pt_mod


def _make_user(db_session, *, approved=True):
    """Insert an IdentityMap row so require_approved() passes."""
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    db_session.add(models.IdentityMap(
        session_id=f"tg_{user_id[:6]}",
        hashed_id=user_id,
        real_id=f"real-{user_id}",
        is_approved=approved,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))
    db_session.commit()
    return user_id


def _make_epic(db_session, *, user_id):
    epic = models.Epic(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title="Test Epic",
        description="Test",
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(epic)
    db_session.commit()
    return epic


class _NonClosingSession:
    """Proxy that forwards everything to the underlying session but ignores
    .close() — the test owns the lifecycle, dispatch_task should not be able
    to terminate the test session via its own finally-block close()."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):  # noqa: D401 — intentionally a no-op
        pass


@pytest.fixture
def patched_pt(monkeypatch, db_session):
    """Make project_tasks module use the in-memory test DB and a no-op executor."""
    monkeypatch.setattr(pt_mod, "SessionLocal", lambda: _NonClosingSession(db_session))
    triggered = []

    async def fake_exec(task_id):
        triggered.append(task_id)

    monkeypatch.setattr(pt_mod, "execute_project_task", fake_exec)
    return triggered


@pytest.mark.asyncio
async def test_dispatch_task_creates_queued_not_backlog(db_session, patched_pt):
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    result = await pt_mod.dispatch_task(
        epic_id=epic.id,
        user_id=user_id,
        title="Find PM2.5 data",
        assigned_agent="twinkle_hub_agent",
        spec="Query Taiwan EPA for last 7 days of PM2.5 in Taipei.",
    )
    assert "dispatched" in result.lower()
    # Drain triggered executors so asyncio.all_tasks doesn't leak
    await asyncio.sleep(0)

    row = db_session.query(models.ProjectTask).first()
    assert row is not None
    assert row.status == "queued", "Atomic dispatch must skip backlog"
    assert row.queue_order == 1
    assert row.assigned_agent == "twinkle_hub_agent"
    assert row.type == "immediate"


@pytest.mark.asyncio
async def test_dispatch_task_triggers_executor_for_immediate(db_session, patched_pt):
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    await pt_mod.dispatch_task(
        epic_id=epic.id,
        user_id=user_id,
        title="Immediate work",
        assigned_agent="coding_agent",
        spec="Write hello.py.",
    )
    # Yield once so the asyncio.create_task scheduling actually runs
    await asyncio.sleep(0)
    assert len(patched_pt) == 1, "Executor should be triggered exactly once"


@pytest.mark.asyncio
async def test_dispatch_task_does_not_trigger_executor_for_scheduled(db_session, patched_pt):
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    result = await pt_mod.dispatch_task(
        epic_id=epic.id,
        user_id=user_id,
        title="Weekly report",
        assigned_agent="business_analysis_agent",
        spec="Generate weekly report.",
        cron="0 9 * * MON",
    )
    await asyncio.sleep(0)
    assert "dispatched" in result.lower()
    row = db_session.query(models.ProjectTask).first()
    assert row.type == "scheduled"
    assert row.status == "scheduled", "Cron tasks start as scheduled, not queued"
    assert len(patched_pt) == 0, "Scheduled tasks must NOT auto-trigger executor"


@pytest.mark.asyncio
async def test_dispatch_task_appends_to_queue(db_session, patched_pt):
    """Second dispatch to the same agent gets queue_order = 2."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="First",
        assigned_agent="coding_agent", spec="step 1",
    )
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="Second",
        assigned_agent="coding_agent", spec="step 2",
    )
    await asyncio.sleep(0)

    rows = (
        db_session.query(models.ProjectTask)
        .order_by(models.ProjectTask.queue_order.asc())
        .all()
    )
    assert [r.queue_order for r in rows] == [1, 2]
    assert [r.title for r in rows] == ["First", "Second"]


@pytest.mark.asyncio
async def test_dispatch_task_per_agent_queue_isolation(db_session, patched_pt):
    """queue_order is per-agent — coding's and BA's queues do not interleave."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="C1",
        assigned_agent="coding_agent", spec="c1",
    )
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="B1",
        assigned_agent="business_analysis_agent", spec="b1",
    )
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="C2",
        assigned_agent="coding_agent", spec="c2",
    )
    await asyncio.sleep(0)

    coding = db_session.query(models.ProjectTask).filter_by(
        assigned_agent="coding_agent"
    ).order_by(models.ProjectTask.queue_order.asc()).all()
    ba = db_session.query(models.ProjectTask).filter_by(
        assigned_agent="business_analysis_agent"
    ).order_by(models.ProjectTask.queue_order.asc()).all()

    assert [r.queue_order for r in coding] == [1, 2]
    assert [r.queue_order for r in ba] == [1]


@pytest.mark.asyncio
async def test_dispatch_task_requires_assigned_agent(db_session, patched_pt):
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    result = await pt_mod.dispatch_task(
        epic_id=epic.id,
        user_id=user_id,
        title="No agent",
        assigned_agent="",
        spec="...",
    )
    assert "Error" in result
    assert "assigned_agent" in result
    assert db_session.query(models.ProjectTask).count() == 0


@pytest.mark.asyncio
async def test_dispatch_task_auto_chains_when_session_has_in_progress_task(db_session, patched_pt):
    """When a second dispatch arrives for the same (user_id, session_id) while
    an earlier task is still queued/doing, the second one MUST be auto-linked
    via depends_on and inserted as backlog — not raced against the first.

    This is the executor-side guarantee that backs Principle 3 ("one
    specialist at a time"). The Manager LLM is supposed to enforce it via
    prompt rules but is unreliable; this test pins down the structural
    safety net."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)
    session_id = "tg_user_session_xyz"

    # First dispatch — no in-progress task → queued, executor triggered.
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id,
        title="Step 1 (Coding)", assigned_agent="coding_agent",
        spec="load wine dataset", session_id=session_id,
    )
    await asyncio.sleep(0)
    assert len(patched_pt) == 1, "First dispatch should trigger executor immediately"

    # Second dispatch in same session, no explicit depends_on
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id,
        title="Step 2 (BA)", assigned_agent="business_analysis_agent",
        spec="write report", session_id=session_id,
    )
    await asyncio.sleep(0)

    rows = (
        db_session.query(models.ProjectTask)
        .order_by(models.ProjectTask.created_at.asc())
        .all()
    )
    coding, ba = rows[0], rows[1]
    assert coding.status == "queued"
    assert ba.status == "backlog", "Auto-linked task must start as backlog, not queued"
    assert ba.depends_on == coding.id, "Auto-link must wire depends_on to upstream"
    assert len(patched_pt) == 1, "Auto-linked task must NOT trigger executor immediately"


@pytest.mark.asyncio
async def test_dispatch_task_no_auto_chain_without_session_id(db_session, patched_pt):
    """If session_id is missing, auto-link cannot scope safely — fall back to
    plain queued dispatch."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="T1",
        assigned_agent="coding_agent", spec="x", session_id=None,
    )
    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="T2",
        assigned_agent="coding_agent", spec="y", session_id=None,
    )
    await asyncio.sleep(0)

    rows = (
        db_session.query(models.ProjectTask)
        .order_by(models.ProjectTask.created_at.asc())
        .all()
    )
    assert all(r.status == "queued" for r in rows), \
        "Without session_id, dispatches should not auto-chain"
    assert all(r.depends_on is None for r in rows)


@pytest.mark.asyncio
async def test_dispatch_task_explicit_depends_on_creates_backlog(db_session, patched_pt):
    """When the caller passes depends_on explicitly, the task is backlog
    (waiting on dep) and the executor is NOT auto-triggered."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="T1",
        assigned_agent="coding_agent", spec="x",
    )
    await asyncio.sleep(0)
    t1 = db_session.query(models.ProjectTask).first()
    assert len(patched_pt) == 1

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="T2",
        assigned_agent="business_analysis_agent", spec="y",
        depends_on=t1.id,
    )
    await asyncio.sleep(0)

    t2 = (
        db_session.query(models.ProjectTask)
        .filter_by(title="T2").first()
    )
    assert t2.status == "backlog"
    assert t2.depends_on == t1.id
    assert len(patched_pt) == 1, "Explicit-depends_on task must not trigger executor"


@pytest.mark.asyncio
async def test_dispatch_task_no_auto_chain_when_prior_is_done(db_session, patched_pt):
    """A done upstream task is not in-progress → next dispatch starts fresh
    (no auto-link), so unrelated user requests don't accumulate phantom deps."""
    user_id = _make_user(db_session)
    epic = _make_epic(db_session, user_id=user_id)
    session_id = "tg_session_done"

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="Earlier (done)",
        assigned_agent="coding_agent", spec="x", session_id=session_id,
    )
    # Mark first task done — simulates prior request completing earlier
    first = db_session.query(models.ProjectTask).first()
    first.status = "done"
    db_session.commit()
    await asyncio.sleep(0)

    await pt_mod.dispatch_task(
        epic_id=epic.id, user_id=user_id, title="New unrelated request",
        assigned_agent="twinkle_hub_agent", spec="z", session_id=session_id,
    )
    await asyncio.sleep(0)

    new_task = (
        db_session.query(models.ProjectTask)
        .filter_by(title="New unrelated request").first()
    )
    assert new_task.status == "queued"
    assert new_task.depends_on is None


@pytest.mark.asyncio
async def test_dispatch_task_rejects_unapproved_user(db_session, patched_pt):
    """An unapproved IdentityMap row → require_approved returns an error string;
    no task is created."""
    user_id = _make_user(db_session, approved=False)
    epic = _make_epic(db_session, user_id=user_id)

    result = await pt_mod.dispatch_task(
        epic_id=epic.id,
        user_id=user_id,
        title="Should be blocked",
        assigned_agent="coding_agent",
        spec="...",
    )
    # require_approved returns a string; dispatch_task returns it verbatim
    assert isinstance(result, str)
    # No task should have been inserted
    assert db_session.query(models.ProjectTask).count() == 0
