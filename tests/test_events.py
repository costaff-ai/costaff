"""Regression test for mcp_servers.tools.events.read_today_events.

Two bugs once made the Nightly Diary RegularWork always say "no events":
  1. `event_data::text LIKE '%user_id%'` — user_id is not in event_data
  2. No date filter, so even if (1) had matched, it returned all-time events

This test creates `events` and `sessions` tables directly on the test
session's engine, monkey-patches `SessionLocal` inside the events module
to use that engine, and checks the function returns ONLY today's events
for the given user_id.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text as sa_text


def _utcnow() -> datetime:
    """Tz-aware UTC `now`. Tests must use this, not `datetime.now()`, because
    the production query path computes day boundaries with `datetime.now(tz)`
    (UTC by default) — naive local-time `now()` would land in tomorrow when
    re-tagged as UTC and the day filter would miss it."""
    return datetime.now(timezone.utc)


def _create_adk_tables(engine):
    """ADK owns these tables in production; in tests we mint a minimal version."""
    with engine.connect() as conn:
        conn.execute(sa_text("""
            CREATE TABLE sessions (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                app_name VARCHAR
            )
        """))
        conn.execute(sa_text("""
            CREATE TABLE events (
                id VARCHAR PRIMARY KEY,
                session_id VARCHAR NOT NULL,
                event_data TEXT NOT NULL,
                "timestamp" DATETIME NOT NULL
            )
        """))
        conn.commit()


def _add_session(db, session_id: str, user_id: str):
    db.execute(sa_text(
        "INSERT INTO sessions (id, user_id, app_name) VALUES (:sid, :uid, 'costaff_agent')"
    ), {"sid": session_id, "uid": user_id})
    db.commit()


def _add_event(db, session_id: str, author: str, text: str, when: datetime):
    """Store events with tz-aware UTC timestamps. Caller should pass values
    from `_utcnow()` (or arithmetic on it); raw `datetime.now()` is naive
    local time and would land in the wrong UTC day when slammed with UTC tz."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    ed = {"author": author, "content": {"role": author, "parts": [{"text": text}]}}
    db.execute(sa_text(
        "INSERT INTO events (id, session_id, event_data, \"timestamp\") "
        "VALUES (:id, :sid, :ed, :ts)"
    ), {
        "id": str(uuid.uuid4()),
        "sid": session_id,
        "ed": json.dumps(ed),
        "ts": when,
    })
    db.commit()


@pytest.fixture
def events_module(db_session, monkeypatch):
    """Create events/sessions tables on the test engine and patch the
    module-level SessionLocal so read_today_events uses our test DB."""
    engine = db_session.bind
    _create_adk_tables(engine)
    from mcp_servers.tools import events as events_mod
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(events_mod, "SessionLocal", sessionmaker(bind=engine))
    return events_mod


def test_returns_no_events_message_when_user_has_none(events_module, db_session):
    out = asyncio.run(events_module.read_today_events("user-with-no-data"))
    assert "No events found" in out


def test_returns_today_events_for_correct_user(events_module, db_session):
    """The fix: link via sessions.user_id, not substring match in event_data."""
    _add_session(db_session, "sess-1", "alice")
    _add_event(db_session, "sess-1", "user", "Hello agent", _utcnow())
    _add_event(db_session, "sess-1", "costaff_agent", "Hi Alice!", _utcnow())

    out = asyncio.run(events_module.read_today_events("alice"))

    assert "Hello agent" in out
    assert "Hi Alice" in out
    assert "[user]" in out
    assert "[costaff_agent]" in out


def test_excludes_other_users_events(events_module, db_session):
    _add_session(db_session, "sess-alice", "alice")
    _add_session(db_session, "sess-bob", "bob")
    _add_event(db_session, "sess-alice", "user", "alice's message", _utcnow())
    _add_event(db_session, "sess-bob", "user", "bob's secret", _utcnow())

    out = asyncio.run(events_module.read_today_events("alice"))

    assert "alice's message" in out
    assert "bob's secret" not in out  # critical: no cross-user leakage


def test_excludes_yesterdays_events(events_module, db_session):
    """The other half of the fix: a date filter so we don't pull all-time
    events. Otherwise diaries would summarize the agent's entire history."""
    _add_session(db_session, "sess-1", "alice")
    yesterday = _utcnow() - timedelta(days=2)  # safely in the past
    today_msg = _utcnow()
    _add_event(db_session, "sess-1", "user", "old message", yesterday)
    _add_event(db_session, "sess-1", "user", "today message", today_msg)

    out = asyncio.run(events_module.read_today_events("alice"))

    assert "today message" in out
    assert "old message" not in out


def test_date_str_param_targets_a_specific_past_day(events_module, db_session):
    """Backfill use case: pass an explicit YYYY-MM-DD to fetch events for
    that single day only — yesterday's events come through, today's don't."""
    _add_session(db_session, "sess-1", "alice")
    yday = _utcnow() - timedelta(days=1)
    yday_str = yday.strftime("%Y-%m-%d")
    _add_event(db_session, "sess-1", "user", "yesterday's message", yday)
    _add_event(db_session, "sess-1", "user", "today's message", _utcnow())

    out = asyncio.run(events_module.read_today_events("alice", date_str=yday_str))

    assert "yesterday's message" in out
    assert "today's message" not in out


def test_date_str_invalid_format_returns_helpful_error(events_module, db_session):
    out = asyncio.run(events_module.read_today_events("alice", date_str="not-a-date"))
    assert "Invalid date_str" in out


def test_event_data_substring_does_not_falsely_match(events_module, db_session):
    """Reject the original buggy behaviour: even if user_id appears as a
    substring inside some other user's event_data JSON, we must NOT return it.
    The new query joins sessions.user_id, so this can't happen."""
    _add_session(db_session, "sess-bob", "bob")
    # Bob's event mentions "alice" in text — old code would have leaked it
    _add_event(db_session, "sess-bob", "user",
               "I am bob talking about alice", _utcnow())

    out = asyncio.run(events_module.read_today_events("alice"))

    assert "I am bob" not in out
    assert "No events found" in out  # alice has no session today
