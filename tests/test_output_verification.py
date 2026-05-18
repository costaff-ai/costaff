"""Tests for the executor's declared-output verification.

The executor must NOT mark a task `done` if the sub-agent's RESULT claims
output files that are not on disk. Otherwise a downstream agent in a chain
reads the spec, looks for the file, and silently fails — 30+ seconds after
the user has already been told the upstream step succeeded.

These tests cover the pure verifier helper (no DB / no ADK / no Telegram)
and the executor's wiring of it (executor must raise → mark task failed).
"""
import os
import uuid
import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from core import models
from mcp_servers.executors import project_task as executor_mod
from mcp_servers.executors.project_task import (
    OutputVerificationError,
    _agent_slot,
    _verify_declared_outputs,
)


# ---------------------------------------------------------------------------
# _agent_slot — name normalisation
# ---------------------------------------------------------------------------

def test_agent_slot_strips_agent_suffix_and_hyphenates():
    assert _agent_slot("coding") == "costaff-agent-coding"
    assert _agent_slot("coding_agent") == "costaff-agent-coding"
    assert _agent_slot("business_analysis") == "costaff-agent-business-analysis"
    assert _agent_slot("business_analysis_agent") == "costaff-agent-business-analysis"
    assert _agent_slot("twinkle_hub_agent") == "costaff-agent-twinkle-hub"
    assert _agent_slot("costaff-agent-coding") == "costaff-agent-coding"


def test_agent_slot_returns_none_for_manager_and_blank():
    assert _agent_slot(None) is None
    assert _agent_slot("") is None
    assert _agent_slot("costaff_agent") is None  # manager itself has no slot


# ---------------------------------------------------------------------------
# _verify_declared_outputs — pure helper, no executor, no DB
# ---------------------------------------------------------------------------

def test_returns_empty_when_no_paths_mentioned():
    """A result with no /app/data/* paths is valid — task may have produced no files."""
    assert _verify_declared_outputs(
        "Everything went fine. No files produced.", "coding"
    ) == []


def test_returns_empty_when_text_is_empty():
    assert _verify_declared_outputs("", "coding") == []
    assert _verify_declared_outputs(None, "coding") == []  # type: ignore[arg-type]


def test_returns_empty_when_no_agent_name():
    """No assigned_agent → nothing to scope against → skip verification."""
    assert _verify_declared_outputs(
        "saved /app/data/shared/costaff-agent-coding/x/file.csv", None
    ) == []
    assert _verify_declared_outputs(
        "saved /app/data/shared/costaff-agent-coding/x/file.csv", "costaff_agent"
    ) == []


def test_only_flags_paths_in_this_agents_own_slot():
    """Critical false-positive guard: when BA's result mentions Coding's
    upstream CSV (as an input reference), the verifier must NOT flag it.

    Reproduced 2026-05-15 on VM: BA mentioned
    /app/data/shared/costaff-agent-coding/sklearn-wine-dataset/wine_dataset.csv
    in its 'I read from ...' summary; verifier flagged it as a missing
    declared output, which marked BA failed even though BA's own PDF
    was successfully written.
    """
    ba_result = (
        "I read /app/data/shared/costaff-agent-coding/wine/wine.csv "
        "and wrote /app/data/shared/costaff-agent-business-analysis/"
        "wine-report/report.pdf"
    )
    # Verifying for BA: Coding's path is an input, not a declared output.
    # Nothing in BA's own slot is missing in this text (the BA path is
    # mentioned but not on disk in this unit test — but it IS in slot, so
    # it WILL flag; that's correct, and tested separately below). Here we
    # just assert the Coding path is NOT among the missing list.
    missing = _verify_declared_outputs(ba_result, "business_analysis")
    assert "/app/data/shared/costaff-agent-coding/wine/wine.csv" not in missing


def test_deduplicates_repeated_in_slot_mentions():
    """Same missing in-slot path mentioned twice → only appears once."""
    text = (
        "see /app/data/shared/costaff-agent-coding/p/x.csv and again "
        "/app/data/shared/costaff-agent-coding/p/x.csv"
    )
    missing = _verify_declared_outputs(text, "coding")
    assert missing == ["/app/data/shared/costaff-agent-coding/p/x.csv"]


def test_recognised_extensions_only():
    """Only files with the recognised extension list count."""
    # `.tar.gz` is not in the extension list — should not be picked up
    assert _verify_declared_outputs(
        "see /app/data/shared/costaff-agent-coding/foo.tar.gz", "coding"
    ) == []


def test_structured_envelope_files_are_verified_in_slot(monkeypatch):
    """When a sub-agent emits a structured envelope, the verifier should
    use the explicit `files:` list (filtered to its own slot) instead of
    regex over prose."""
    # Stub os.path.isfile so we control which paths "exist".
    real = "/app/data/shared/costaff-agent-coding/wine/exists.csv"
    fake = "/app/data/shared/costaff-agent-coding/wine/missing.pdf"
    monkeypatch.setattr(
        executor_mod.os.path, "isfile",
        lambda p: p == real,
    )
    raw = f"""[RESULT_START]
status: ok
summary: produced one csv but pdf was meant to be there too
files:
  - {real}
  - {fake}
[RESULT_END]"""
    missing = _verify_declared_outputs(raw, "coding")
    assert missing == [fake]


def test_structured_envelope_only_checks_in_slot_files(monkeypatch):
    """If the structured envelope lists files from OTHER agents' slots (e.g.
    BA's envelope mentions Coding's input CSV that may not yet exist), only
    BA's own slot files are verified."""
    monkeypatch.setattr(
        executor_mod.os.path, "isfile",
        lambda p: False,  # nothing exists
    )
    raw = """[RESULT_START]
status: ok
files:
  - /app/data/shared/costaff-agent-coding/upstream/input.csv
  - /app/data/shared/costaff-agent-business-analysis/wine-report/report.pdf
[RESULT_END]"""
    # Verify for BA — only the BA-slot path counts as a declared output
    missing = _verify_declared_outputs(raw, "business_analysis")
    assert missing == [
        "/app/data/shared/costaff-agent-business-analysis/wine-report/report.pdf"
    ]


def test_structured_envelope_empty_files_is_valid():
    """`status: ok` with empty `files:` (e.g. pure-query agent that produced
    no artefact) must NOT trigger verification failure."""
    raw = """[RESULT_START]
status: ok
summary: queried 49 rows, no file artefact produced
files:
[RESULT_END]"""
    assert _verify_declared_outputs(raw, "twinkle_hub") == []


# ---------------------------------------------------------------------------
# Executor wiring — verification failure routes through the failure branch
# ---------------------------------------------------------------------------

class _NonClosingSession:
    def __init__(self, inner): self._inner = inner
    def __getattr__(self, name): return getattr(self._inner, name)
    def close(self): pass


def _make_task(db_session, *, session_id=None):
    epic = models.Epic(
        id=str(uuid.uuid4()), user_id="user_x", title="E",
        status="active", created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(epic)
    task = models.ProjectTask(
        id=str(uuid.uuid4()),
        epic_id=epic.id,
        user_id="user_x",
        session_id=session_id,
        title="Pretend to write a CSV",
        spec="Generate a CSV at /app/data/shared/foo/x.csv.",
        type="immediate",
        assigned_agent="coding_agent",
        status="queued",
        channel="telegram",
        recipient="user_x",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(task)
    db_session.commit()
    return task


@pytest.mark.asyncio
async def test_executor_marks_failed_when_verifier_returns_missing(db_session, monkeypatch):
    """Enabled-mode contract: with COSTAFF_VERIFY_DECLARED_OUTPUTS=1 the
    verifier flagging missing in-slot outputs → executor marks task failed
    (not done), records issue comment.

    We stub the verifier itself to isolate executor-wiring behaviour from
    the slot/regex logic (which is covered by the pure-helper tests above).
    """
    monkeypatch.setenv("COSTAFF_VERIFY_DECLARED_OUTPUTS", "1")
    # grace retry uses real `await asyncio.sleep`; no-op it so the test
    # doesn't wait the ~10s grace before the (still-missing) raise.
    async def _no_sleep(*_a, **_k):
        return None
    monkeypatch.setattr(executor_mod.asyncio, "sleep", _no_sleep)
    task = _make_task(db_session)
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: _NonClosingSession(db_session))

    fake_missing = "/app/data/shared/costaff-agent-coding/p/ghost.csv"
    monkeypatch.setattr(
        executor_mod, "_verify_declared_outputs",
        lambda text, agent: [fake_missing],
    )

    async def fake_run(app, uid, sid, prompt):
        return f"[RESULT_START] done [RESULT_END]"

    async def fake_dispatch(channel, recipient, body, sid):
        return None

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.refresh(task)
    assert task.status == "failed", "Missing declared outputs must fail the task"

    issues = (
        db_session.query(models.TaskComment)
        .filter_by(task_id=task.id, type="issue")
        .all()
    )
    assert len(issues) == 1
    assert fake_missing in issues[0].content
    assert "OutputVerificationError" in issues[0].content


@pytest.mark.asyncio
async def test_executor_does_not_fail_when_verification_disabled(db_session, monkeypatch):
    """New default contract: COSTAFF_VERIFY_DECLARED_OUTPUTS unset → missing
    declared outputs only WARN; the task still completes (status != failed),
    no OutputVerificationError issue comment. (Verification disabled because
    it false-failed successful tasks and became a pipeline bottleneck.)
    """
    monkeypatch.delenv("COSTAFF_VERIFY_DECLARED_OUTPUTS", raising=False)
    task = _make_task(db_session)
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(
        executor_mod, "_verify_declared_outputs",
        lambda text, agent: ["/app/data/shared/costaff-agent-coding/p/ghost.csv"],
    )

    async def fake_run(app, uid, sid, prompt):
        return "[RESULT_START] done [RESULT_END]"

    async def fake_dispatch(channel, recipient, body, sid):
        return None

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.refresh(task)
    assert task.status != "failed", "Disabled verification must NOT fail the task"
    issues = (
        db_session.query(models.TaskComment)
        .filter_by(task_id=task.id, type="issue")
        .all()
    )
    assert not any("OutputVerificationError" in i.content for i in issues)


@pytest.mark.asyncio
async def test_executor_marks_done_when_verifier_returns_empty(db_session, monkeypatch):
    """Symmetric case: verifier returns [] → task completes normally."""
    task = _make_task(db_session)
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(
        executor_mod, "_verify_declared_outputs",
        lambda text, agent: [],
    )

    async def fake_run(app, uid, sid, prompt):
        return "[RESULT_START] done, wrote /app/data/shared/costaff-agent-coding/p/x.csv [RESULT_END]"

    async def fake_dispatch(channel, recipient, body, sid):
        return None

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.refresh(task)
    assert task.status == "done"


@pytest.mark.asyncio
async def test_executor_ignores_other_agents_paths(db_session, monkeypatch):
    """Regression for the 2026-05-15 VM false-positive: BA's RESULT mentions
    Coding's CSV (as an input reference). Verifier must NOT fail BA just
    because that upstream path does not exist on disk."""
    task = _make_task(db_session)
    # Re-purpose this task as a BA task
    task.assigned_agent = "business_analysis"
    db_session.commit()

    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: _NonClosingSession(db_session))

    async def fake_run(app, uid, sid, prompt):
        return (
            "[RESULT_START] I read /app/data/shared/costaff-agent-coding/"
            "wine/wine.csv (does not actually exist) and wrote nothing to "
            "my own slot. [RESULT_END]"
        )

    async def fake_dispatch(channel, recipient, body, sid):
        return None

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.refresh(task)
    assert task.status == "done", (
        "BA must complete normally even when its RESULT mentions Coding's "
        "input path; only BA's OWN slot is verified"
    )


@pytest.mark.asyncio
async def test_executor_marks_done_when_no_paths_claimed(db_session, monkeypatch):
    """A sub-agent that does not declare any output files (e.g. a pure query
    or analysis with no file artefact) must still complete normally."""
    task = _make_task(db_session)
    monkeypatch.setattr(executor_mod, "SessionLocal", lambda: _NonClosingSession(db_session))

    async def fake_run(app, uid, sid, prompt):
        return "[RESULT_START] Found 49 rows. PM2.5 avg = 17.2 [RESULT_END]"

    async def fake_dispatch(channel, recipient, body, sid):
        return None

    monkeypatch.setattr(executor_mod, "run_adk_prompt", fake_run)
    monkeypatch.setattr(executor_mod, "dispatch_notification", fake_dispatch)

    await executor_mod.execute_project_task(task.id)
    for t in list(asyncio.all_tasks()):
        if t is not asyncio.current_task():
            t.cancel()

    db_session.refresh(task)
    assert task.status == "done"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _re_for(tmp_path: Path):
    """Build a regex that matches absolute paths under tmp_path (so tests can
    use a real temp dir instead of needing to create /app/data/ on the host)."""
    import re as _re
    exts = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"
    prefix = _re.escape(str(tmp_path))
    return _re.compile(prefix + r"/[\w./-]+\.(?:" + exts + r")", _re.IGNORECASE)
