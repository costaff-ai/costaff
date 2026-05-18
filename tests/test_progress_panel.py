"""Progress panel state/render logic — Telegram side mocked out."""
import pytest

from core.notifiers import progress_panel as pp


@pytest.fixture(autouse=True)
def _reset_and_mute(monkeypatch):
    pp._PANELS.clear()
    pp._LOCKS.clear()

    async def _noop_flush(key):
        return None

    # Mute the Telegram side; assert on in-memory state + _render only.
    monkeypatch.setattr(pp, "_flush", _noop_flush)
    yield
    pp._PANELS.clear()
    pp._LOCKS.clear()


def test_render_matches_spec_format():
    state = {
        "agent_disp": "Business Analysis Agent", "header": "Working",
        "steps": [["generate image", "Done"], ["generate report", "Doing"]],
    }
    assert pp._render(state) == (
        "[ Business Analysis Agent ] Working\n"
        "generate image ... Done\n"
        "generate report ... Doing"
    )


@pytest.mark.asyncio
async def test_step_lifecycle_working_then_done():
    K = "task_abc"
    await pp.panel_step(K, "u1", "telegram", K, "business_analysis_agent",
                        "generate_chart", "start", True)
    await pp.panel_step(K, "u1", "telegram", K, "business_analysis_agent",
                        "generate_chart", "end", True)
    await pp.panel_step(K, "u1", "telegram", K, "business_analysis_agent",
                        "export_pdf", "start", True)
    st = pp._PANELS[K]
    assert st["header"] == "Working"
    assert st["steps"] == [["generate_chart", "Done"], ["export_pdf", "Doing"]]

    await pp.panel_finalize(K, "done")
    # finalize renders then drops state
    assert K not in pp._PANELS


@pytest.mark.asyncio
async def test_failed_tool_marks_failed_and_finalize_failed():
    K = "task_xyz"
    await pp.panel_step(K, "u1", "telegram", K, "business_analysis_agent",
                        "export_pdf", "start", True)
    await pp.panel_step(K, "u1", "telegram", K, "business_analysis_agent",
                        "export_pdf", "end", False)
    st = pp._PANELS[K]
    assert st["steps"] == [["export_pdf", "Failed"]]
    txt = pp._render(st)
    assert txt.startswith("[ Business Analysis Agent ] Working")
    assert "export_pdf ... Failed" in txt
    await pp.panel_finalize(K, "failed")
    assert K not in pp._PANELS


@pytest.mark.asyncio
async def test_non_telegram_channel_is_noop():
    await pp.panel_step("k", "u1", "discord", "k", "coding_agent",
                        "run", "start", True)
    assert "k" not in pp._PANELS


@pytest.mark.asyncio
async def test_finalize_unknown_key_safe():
    await pp.panel_finalize("never_seen", "done")  # must not raise
