"""Tests for the send_message_now MCP tool — channel routing, identity
resolution, delivery-status logging, and the webchat branch that batch 2
fixed (it used to return "Sent." without sending anything).

send_message_now dispatches each blocking notifier via asyncio.to_thread,
so we patch the notifier symbols on the module with plain functions and
assert they were called with the resolved target id.
"""
import uuid
from datetime import datetime

import pytest

from core import models
from mcp_servers.tools import messaging as msg_mod


class _NonClosingSession:
    """Forward everything to the test session but ignore .close() — the tool
    opens/closes its own sessions and must not terminate the test's."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


@pytest.fixture
def calls(monkeypatch, db_session):
    """Wire the tool to the in-memory DB and capture every notifier call.

    Each notifier is replaced with a recorder that returns a configurable
    success value (default True). Returns the recorder registry so tests can
    assert on it and flip the return value.
    """
    monkeypatch.setattr(msg_mod, "SessionLocal", lambda: _NonClosingSession(db_session))

    registry = {"sent": [], "files": [], "return_value": True}

    def _text_recorder(name, is_async=False):
        def rec(target, body, **kw):
            registry["sent"].append((name, target, body, kw))
            return registry["return_value"]

        async def arec(target, body, **kw):
            registry["sent"].append((name, target, body, kw))
            return registry["return_value"]

        return arec if is_async else rec

    def _file_recorder(name):
        def rec(target, fp, **kw):
            registry["files"].append((name, target, fp))
            return True
        return rec

    monkeypatch.setattr(msg_mod, "send_telegram_notification", _text_recorder("telegram"))
    monkeypatch.setattr(msg_mod, "send_discord_notification", _text_recorder("discord"))
    monkeypatch.setattr(msg_mod, "send_slack_notification", _text_recorder("slack"))
    monkeypatch.setattr(msg_mod, "send_line_notification", _text_recorder("line", is_async=True))
    monkeypatch.setattr(msg_mod, "send_webchat_notification", _text_recorder("webchat"))
    monkeypatch.setattr(msg_mod, "send_telegram_document", _file_recorder("telegram"))
    monkeypatch.setattr(msg_mod, "send_discord_file", _file_recorder("discord"))
    monkeypatch.setattr(msg_mod, "send_slack_file", _file_recorder("slack"))
    monkeypatch.setattr(msg_mod, "send_webchat_file", _file_recorder("webchat"))
    return registry


def _reminders(db):
    return db.query(models.Reminder).all()


# ---------------------------------------------------------------------------
# guard + routing
# ---------------------------------------------------------------------------

async def test_empty_body_is_rejected_without_sending(calls):
    out = await msg_mod.send_message_now(channel="telegram", recipient="u1", body="  ")
    assert out == "Error: body is required."
    assert calls["sent"] == []


@pytest.mark.parametrize("channel,expected", [
    ("telegram", "telegram"),
    ("tg_costaff_bot", "telegram"),
    ("discord", "discord"),
    ("slack", "slack"),
    ("line", "line"),
    ("webchat", "webchat"),
])
async def test_channel_arg_routes_to_correct_notifier(calls, channel, expected):
    out = await msg_mod.send_message_now(channel=channel, recipient="u1", body="hi")
    assert out == "Sent."
    assert [c[0] for c in calls["sent"]] == [expected]


@pytest.mark.parametrize("session_id,expected", [
    ("tg_abc", "telegram"),
    ("dc_abc", "discord"),
    ("discord_abc", "discord"),
    ("slack_abc", "slack"),
    ("line_abc", "line"),
    ("web_abc", "webchat"),
])
async def test_default_channel_resolves_from_session_prefix(calls, session_id, expected):
    out = await msg_mod.send_message_now(
        channel="default", recipient="u1", body="hi", session_id=session_id)
    assert out == "Sent."
    assert [c[0] for c in calls["sent"]] == [expected]


async def test_unknown_session_prefix_falls_back_to_telegram(calls):
    await msg_mod.send_message_now(
        channel="", recipient="u1", body="hi", session_id="mystery_abc")
    assert [c[0] for c in calls["sent"]] == ["telegram"]


# ---------------------------------------------------------------------------
# webchat branch — the batch-2 fix
# ---------------------------------------------------------------------------

async def test_webchat_branch_actually_sends(calls):
    """Regression: this branch used to return 'Sent.' without calling any
    sender. It must now push through send_webchat_notification."""
    out = await msg_mod.send_message_now(channel="webchat", recipient="u1", body="hi")
    assert out == "Sent."
    assert calls["sent"] == [("webchat", "u1", "hi", {"session_id": None})]


# ---------------------------------------------------------------------------
# identity resolution
# ---------------------------------------------------------------------------

async def test_recipient_resolved_through_identity_map(calls, db_session):
    db_session.add(models.IdentityMap(
        session_id="tg_sess", hashed_id="hashed-1", real_id="real-42",
        is_approved=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    ))
    db_session.commit()

    await msg_mod.send_message_now(channel="telegram", recipient="hashed-1", body="hi")
    # The notifier must receive the real_id, not the hashed_id
    assert calls["sent"][0][1] == "real-42"


# ---------------------------------------------------------------------------
# delivery-status logging
# ---------------------------------------------------------------------------

async def test_success_logs_reminder_sent(calls, db_session):
    out = await msg_mod.send_message_now(
        channel="telegram", recipient="u1", body="hi",
        user_id="user-9", session_id="tg_x")
    assert out == "Sent."
    rows = _reminders(db_session)
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].channel == "telegram"
    assert rows[0].recipient == "u1"
    assert rows[0].user_id == "user-9"


async def test_failure_logs_reminder_failed(calls, db_session):
    calls["return_value"] = False  # notifier reports failure
    out = await msg_mod.send_message_now(channel="telegram", recipient="u1", body="hi")
    assert out == "Failed."
    rows = _reminders(db_session)
    assert len(rows) == 1 and rows[0].status == "failed"


# ---------------------------------------------------------------------------
# file attachments
# ---------------------------------------------------------------------------

async def test_referenced_files_are_attached(calls, monkeypatch):
    # Force the extractor to report one path so we don't touch the filesystem.
    monkeypatch.setattr(msg_mod, "_extract_file_paths", lambda body: ["/app/data/report.pdf"])
    await msg_mod.send_message_now(channel="telegram", recipient="u1", body="see attached")
    assert calls["files"] == [("telegram", "u1", "/app/data/report.pdf")]
