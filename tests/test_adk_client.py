"""Tests for core.adk_client.run_adk_prompt response parsing.

Regression focus: an agent event whose only text part is "" (a tool-only
final turn) must NOT be returned as the result — it should trigger the
summarize retry, and only fall back to the ⚠️ sentinel when nothing usable
comes back. Otherwise the executor marks the task done with empty content.
"""
import pytest

import core.adk_client as adk


class _FakeResp:
    def __init__(self, events):
        self.status_code = 200
        self._events = events

    def json(self):
        return self._events


class _FakeClient:
    """Returns a queued response per POST call."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.post_count = 0

    async def post(self, url, json=None, headers=None):
        self.post_count += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch):
    async def _ok_session(app, uid, sid):
        return True
    monkeypatch.setattr(adk, "ensure_session", _ok_session)


async def test_empty_text_part_triggers_summarize_retry(monkeypatch):
    # 1st call: final agent event has only {"text": ""}  → must NOT return ""
    # 2nd call (summarize): returns real text
    client = _FakeClient([
        _FakeResp([{"author": "agent", "content": {"parts": [{"text": ""}]}}]),
        _FakeResp([{"author": "agent", "content": {"parts": [{"text": "Here is the summary."}]}}]),
    ])
    monkeypatch.setattr(adk, "_get_http_client", lambda: client)

    out = await adk.run_adk_prompt("app", "u", "sid_empty", prompt="do it")
    assert out == "Here is the summary."
    assert client.post_count == 2  # empty first turn forced the summarize retry


async def test_returns_latest_nonempty_text(monkeypatch):
    # Final event is tool-only empty, but an earlier event has the real answer.
    client = _FakeClient([
        _FakeResp([
            {"author": "agent", "content": {"parts": [{"text": "Real answer"}]}},
            {"author": "agent", "content": {"parts": [{"text": ""}]}},  # later, empty
        ]),
    ])
    monkeypatch.setattr(adk, "_get_http_client", lambda: client)

    out = await adk.run_adk_prompt("app", "u", "sid_latest", prompt="do it")
    assert out == "Real answer"
    assert client.post_count == 1


async def test_all_empty_exhausts_to_sentinel(monkeypatch):
    # Every attempt yields only empty text → ⚠️ sentinel (executor fails it).
    client = _FakeClient([
        _FakeResp([{"author": "agent", "content": {"parts": [{"text": ""}]}}]) for _ in range(3)
    ])
    monkeypatch.setattr(adk, "_get_http_client", lambda: client)

    out = await adk.run_adk_prompt("app", "u", "sid_allempty", prompt="do it")
    assert out.startswith("⚠️")
    assert client.post_count == 3


async def test_normal_text_returned_first_try(monkeypatch):
    client = _FakeClient([
        _FakeResp([{"author": "agent", "content": {"parts": [{"text": "Done."}]}}]),
    ])
    monkeypatch.setattr(adk, "_get_http_client", lambda: client)

    out = await adk.run_adk_prompt("app", "u", "sid_ok", prompt="do it")
    assert out == "Done."
    assert client.post_count == 1
