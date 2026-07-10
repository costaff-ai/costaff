"""Tests for the notification outbox — no channel push is silently lost.

- A successful dispatch delivers and enqueues nothing.
- A failed dispatch (notifier returns False, or raises) enqueues a pending
  outbox row instead of dropping the result.
- The retry loop re-sends due rows, marks them sent on success, backs off
  on repeated failure, and marks them dead at max_attempts.
"""
from datetime import datetime, timedelta

import pytest

from core import models
import core.notifiers.dispatcher as disp
import mcp_servers.background as bg


@pytest.fixture(autouse=True)
def _wire_db(db_session, monkeypatch):
    monkeypatch.setattr(disp, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bg, "SessionLocal", lambda: db_session)
    # Neutralize IdentityMap lookup inside _send_to_channel (no rows needed)
    yield


def _outbox(db):
    return db.query(models.NotificationOutbox).all()


async def test_successful_dispatch_enqueues_nothing(db_session, monkeypatch):
    async def ok_send(channel, recipient, message, session_id=None):
        return True
    monkeypatch.setattr(disp, "_send_to_channel", ok_send)

    delivered = await disp.dispatch_notification("telegram", "u1", "hi")
    assert delivered is True
    assert _outbox(db_session) == []


async def test_failed_dispatch_enqueues_pending_row(db_session, monkeypatch):
    async def fail_send(channel, recipient, message, session_id=None):
        return False
    monkeypatch.setattr(disp, "_send_to_channel", fail_send)

    delivered = await disp.dispatch_notification("telegram", "u1", "hi", session_id="tg_1")
    assert delivered is False
    rows = _outbox(db_session)
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].channel == "telegram"
    assert rows[0].message == "hi"
    assert rows[0].session_id == "tg_1"


async def test_raising_send_is_caught_and_enqueued(db_session, monkeypatch):
    async def boom_send(channel, recipient, message, session_id=None):
        raise RuntimeError("telegram 500")
    monkeypatch.setattr(disp, "_send_to_channel", boom_send)

    delivered = await disp.dispatch_notification("telegram", "u1", "hi")
    assert delivered is False
    rows = _outbox(db_session)
    assert len(rows) == 1 and rows[0].status == "pending"
    assert "500" in (rows[0].last_error or "")


async def test_enqueue_on_failure_false_does_not_enqueue(db_session, monkeypatch):
    """The retry loop passes enqueue_on_failure=False so a repeat failure
    updates the existing row instead of spawning a new one."""
    async def fail_send(channel, recipient, message, session_id=None):
        return False
    monkeypatch.setattr(disp, "_send_to_channel", fail_send)

    delivered = await disp.dispatch_notification(
        "telegram", "u1", "hi", enqueue_on_failure=False)
    assert delivered is False
    assert _outbox(db_session) == []


async def test_retry_loop_marks_sent_on_success(db_session, monkeypatch):
    db_session.add(models.NotificationOutbox(
        channel="telegram", recipient="u1", message="hi", status="pending",
        attempts=0, max_attempts=8, next_attempt_at=datetime.utcnow() - timedelta(minutes=1),
    ))
    db_session.commit()

    async def ok_dispatch(channel, recipient, message, session_id=None, enqueue_on_failure=True):
        assert enqueue_on_failure is False  # retry must not re-enqueue
        return True
    monkeypatch.setattr(bg, "dispatch_notification", ok_dispatch, raising=False)
    # bg imports dispatch_notification lazily inside process_outbox_once
    monkeypatch.setattr(disp, "dispatch_notification", ok_dispatch)

    sent = await bg.process_outbox_once()
    assert sent == 1
    assert _outbox(db_session)[0].status == "sent"


async def test_retry_loop_backs_off_then_dies(db_session, monkeypatch):
    row = models.NotificationOutbox(
        channel="telegram", recipient="u1", message="hi", status="pending",
        attempts=7, max_attempts=8,
        next_attempt_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db_session.add(row)
    db_session.commit()

    async def fail_dispatch(channel, recipient, message, session_id=None, enqueue_on_failure=True):
        return False
    monkeypatch.setattr(disp, "dispatch_notification", fail_dispatch)

    sent = await bg.process_outbox_once()
    assert sent == 0
    refreshed = _outbox(db_session)[0]
    assert refreshed.attempts == 8
    assert refreshed.status == "dead"  # hit max_attempts


async def test_send_treats_none_return_as_failure(db_session, monkeypatch):
    """Regression: LINE's notifier returns None when its token is missing.
    _send_to_channel must treat a non-True result as failure (was
    `ok is not False`, which swallowed None as success and skipped the
    outbox → silent message loss)."""
    async def line_none(target, body):
        return None  # LINE with a missing access token
    monkeypatch.setattr(disp, "send_line_notification", line_none)

    ok = await disp._send_to_channel("line", "u1", "hi")
    assert ok is False

    # And via the full dispatch path it must enqueue for retry, not vanish
    delivered = await disp.dispatch_notification("line", "u1", "hi")
    assert delivered is False
    rows = _outbox(db_session)
    assert len(rows) == 1 and rows[0].status == "pending" and rows[0].channel == "line"


async def test_retry_loop_skips_not_yet_due(db_session, monkeypatch):
    db_session.add(models.NotificationOutbox(
        channel="telegram", recipient="u1", message="hi", status="pending",
        attempts=1, max_attempts=8,
        next_attempt_at=datetime.utcnow() + timedelta(minutes=10),  # future
    ))
    db_session.commit()

    called = []

    async def spy_dispatch(*a, **k):
        called.append(1)
        return True
    monkeypatch.setattr(disp, "dispatch_notification", spy_dispatch)

    sent = await bg.process_outbox_once()
    assert sent == 0 and called == []  # future row is not touched
    assert _outbox(db_session)[0].status == "pending"
