"""Tests for orphan-task recovery (background.recover_orphaned_tasks).

Contract (GA batch 2):
- Startup call (max_age_minutes=0): EVERY 'doing' row is reaped immediately —
  all executors died with the previous process, so there is no legitimate
  'doing' row at startup. (The old 30-minute age gate left a window where a
  restart within 30 minutes of a task starting stranded it forever.)
- Periodic sweep (default age): rows younger than the threshold are left
  alone, and rows registered in RUNNING_TASKS (live executor in this
  process) are never touched regardless of age.
- Reaped tasks go through fail_task_and_notify: status='failed', an issue
  TaskComment, a user notification when channel/recipient resolve, and a
  queue advance that wakes dependents.
- Tasks in other statuses are untouched.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest

from core import models
from mcp_servers import background
from mcp_servers.executors import project_task as executor_mod


def _make_task(db, *, status, age_minutes, title="t", channel=None,
               recipient=None, depends_on=None):
    """Helper: insert a ProjectTask whose updated_at is `age_minutes` in the past."""
    epic = models.Epic(
        id=str(uuid.uuid4()),
        user_id="u",
        title="E",
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(epic)
    db.flush()
    t = models.ProjectTask(
        id=str(uuid.uuid4()),
        epic_id=epic.id,
        user_id="u",
        title=title,
        spec="...",
        type="immediate",
        assigned_agent="ba",
        status=status,
        channel=channel,
        recipient=recipient,
        depends_on=depends_on,
        created_at=datetime.utcnow() - timedelta(minutes=age_minutes),
        updated_at=datetime.utcnow() - timedelta(minutes=age_minutes),
    )
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def wired(db_session, monkeypatch):
    """Patch both modules onto the test DB and neutralize side channels."""
    monkeypatch.setattr(background, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: db_session)

    sent = []

    async def fake_dispatch(channel, recipient, body, sid):
        sent.append((channel, recipient, body, sid))

    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)
    executor_mod.RUNNING_TASKS.clear()
    yield sent
    executor_mod.RUNNING_TASKS.clear()


async def _drain():
    """Let fire-and-forget queue-advance tasks run, then cancel leftovers."""
    await asyncio.sleep(0)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()


async def test_startup_age_zero_reaps_fresh_doing(db_session, wired):
    """The restart window: a task that started 2 minutes ago must be reaped
    by the startup pass — its worker died with the old process."""
    fresh = _make_task(db_session, status="doing", age_minutes=2, title="fresh")

    recovered = await background.recover_orphaned_tasks(max_age_minutes=0)
    await _drain()
    assert recovered == 1

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, fresh.id).status == "failed"
    comments = db_session.query(models.TaskComment).filter(
        models.TaskComment.task_id == fresh.id
    ).all()
    assert len(comments) == 1
    assert comments[0].type == "issue"
    assert "orphan" in comments[0].content.lower()


async def test_sweep_skips_running_and_young_tasks(db_session, wired):
    old_orphan_id = _make_task(db_session, status="doing", age_minutes=60, title="orphan").id
    old_live_id = _make_task(db_session, status="doing", age_minutes=60, title="live").id
    young_id = _make_task(db_session, status="doing", age_minutes=2, title="young").id
    queued_id = _make_task(db_session, status="queued", age_minutes=60, title="queued").id
    done_id = _make_task(db_session, status="done", age_minutes=60, title="done").id

    # `old_live` has a live executor in this process — must never be reaped,
    # no matter how long it has been running.
    executor_mod.RUNNING_TASKS.add(old_live_id)

    recovered = await background.recover_orphaned_tasks()
    await _drain()
    assert recovered == 1

    db_session.expire_all()
    statuses = {t.id: t.status for t in db_session.query(models.ProjectTask).all()}
    assert statuses[old_orphan_id] == "failed"
    assert statuses[old_live_id] == "doing"
    assert statuses[young_id] == "doing"
    assert statuses[queued_id] == "queued"
    assert statuses[done_id] == "done"


async def test_reaped_task_notifies_user(db_session, wired):
    sent = wired
    _make_task(db_session, status="doing", age_minutes=60,
               title="notify-me", channel="telegram", recipient="12345")

    assert await background.recover_orphaned_tasks() == 1
    await _drain()

    assert len(sent) == 1
    channel, recipient, body, _sid = sent[0]
    assert (channel, recipient) == ("telegram", "12345")
    assert "notify-me" in body and "failed" in body


async def test_reaped_task_wakes_backlog_dependent(db_session, wired):
    """Recovery must advance the queue so dependents don't strand in backlog.
    The woken dependent then fails via the cascade (upstream failed)."""
    upstream_id = _make_task(db_session, status="doing", age_minutes=60, title="up").id
    downstream_id = _make_task(db_session, status="backlog", age_minutes=60,
                               title="down", depends_on=upstream_id).id

    assert await background.recover_orphaned_tasks() == 1
    # Drain the queue-advance + cascaded execute without cancelling them
    for _ in range(10):
        await asyncio.sleep(0)
    await _drain()

    db_session.expire_all()
    assert db_session.get(models.ProjectTask, upstream_id).status == "failed"
    # Dependent must have left backlog (promoted, then cascade-failed)
    assert db_session.get(models.ProjectTask, downstream_id).status == "failed"


async def test_returns_zero_when_nothing_stuck(db_session, wired):
    _make_task(db_session, status="doing", age_minutes=2)
    _make_task(db_session, status="done", age_minutes=60)
    assert await background.recover_orphaned_tasks() == 0
    await _drain()


async def test_recovers_multiple_orphans(db_session, wired):
    for _ in range(3):
        _make_task(db_session, status="doing", age_minutes=60)

    assert await background.recover_orphaned_tasks() == 3
    await _drain()
    remaining = db_session.query(models.ProjectTask).filter(
        models.ProjectTask.status == "doing"
    ).count()
    assert remaining == 0


async def test_poll_skips_dependency_blocked_and_fires_ready(db_session, wired, monkeypatch):
    """Regression: a queued-but-blocked front task must not occupy the agent
    slot and starve a READY task behind it in the same agent's queue."""
    fired = []

    async def fake_exec(tid):
        fired.append(tid)

    monkeypatch.setattr(background, "execute_project_task", fake_exec)

    # upstream not done → downstream (queue_order 1) is blocked; ready task
    # (queue_order 2, same agent, no dep) must still fire.
    upstream = _make_task(db_session, status="queued", age_minutes=1, title="up")
    blocked = _make_task(db_session, status="queued", age_minutes=1, title="blocked", depends_on=upstream.id)
    blocked.queue_order = 1
    ready = _make_task(db_session, status="queued", age_minutes=1, title="ready")
    ready.queue_order = 2
    db_session.commit()
    upstream_id, blocked_id, ready_id = upstream.id, blocked.id, ready.id

    # Let one poll iteration run (and the fired fake_exec tasks execute).
    import asyncio as _aio
    poll = _aio.ensure_future(background.poll_queued_tasks())
    await _aio.sleep(0.05)
    poll.cancel()
    try:
        await poll
    except _aio.CancelledError:
        pass

    # blocked must NOT have fired; ready fires despite being behind it
    assert blocked_id not in fired
    assert ready_id in fired
