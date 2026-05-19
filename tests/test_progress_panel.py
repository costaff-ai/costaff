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
    for st in pp._PANELS.values():
        t = st.get("ticker")
        if t is not None:
            t.cancel()
    pp._PANELS.clear()
    pp._LOCKS.clear()


def test_render_matches_spec_format():
    state = {
        "agent_disp": "Business Analysis Agent", "header": "Done",
        "phase": 0, "task_title": "製作台北市居家醫療分布圖表並撰寫報告",
        "steps": [[pp._SEC, "[Action] 分布統計"],
                  ["generate_chart", "Done"],
                  ["create_report_from_markdown", "Done"]],
    }
    assert pp._render(state) == (
        "[ Business Analysis Agent ]\n"
        "-----\n"
        "1. task: 製作台北市居家醫療分布圖表並撰寫報告\n"
        "2. status: Done\n"
        "-----\n"
        "\n"
        "Working Process:\n"
        "- [Action] 分布統計\n"
        "  generate_chart - Done\n"
        "  create_report_from_markdown - Done"
    )


def test_render_status_breathing_dots_cycle():
    state = {
        "agent_disp": "Business Analysis Agent", "header": "Working",
        "task_title": "T", "steps": [["write_report", "Doing"]],
    }
    state["phase"] = 0
    assert "2. status: Working." in pp._render(state)
    state["phase"] = 1
    assert "2. status: Working.." in pp._render(state)
    state["phase"] = 2
    assert "2. status: Working..." in pp._render(state)
    state["phase"] = 3  # wraps back to one dot
    assert "2. status: Working." in pp._render(state)
    # tool lines are static (the pulse lives on the status line)
    assert "  write_report - Doing" in pp._render(state)


def test_render_missing_title_falls_back():
    state = {"agent_disp": "Coding Agent", "header": "Working",
             "phase": 0, "steps": []}
    assert "1. task: —" in pp._render(state)


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
    assert txt.startswith("[ Business Analysis Agent ]\n-----")
    assert "2. status: Working" in txt
    assert "  export_pdf - Failed" in txt
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


@pytest.mark.asyncio
async def test_report_step_tool_maps_status_to_panel():
    from mcp_servers.tools.progress_tool import report_step
    K = "task_rs"
    await report_step(session_id=K, step="generate charts", status="doing",
                      channel="telegram", user_id="u1")
    await report_step(session_id=K, step="generate charts", status="done",
                      channel="telegram", user_id="u1")
    await report_step(session_id=K, step="export pdf", status="failed",
                      channel="telegram", user_id="u1")
    st = pp._PANELS[K]
    assert st["steps"] == [["generate charts", "Done"],
                           ["export pdf", "Failed"]]
    # unknown/blank status defaults to a "doing" start line
    await report_step(session_id=K, step="cleanup", status="",
                      channel="telegram", user_id="u1")
    assert ["cleanup", "Doing"] in pp._PANELS[K]["steps"]


def test_render_groups_tools_under_sections():
    state = {
        "agent_disp": "Coding Agent", "header": "Done", "phase": 0,
        "task_title": "write and run a prime script",
        "steps": [
            [pp._SEC, "[Action] write script"],
            ["mkdir", "Done"],
            ["write_file", "Done"],
            [pp._SEC, "[Action] Executing primes.py"],
            ["run_python_file", "Done"],
        ],
    }
    assert pp._render(state) == (
        "[ Coding Agent ]\n"
        "-----\n"
        "1. task: write and run a prime script\n"
        "2. status: Done\n"
        "-----\n"
        "\n"
        "Working Process:\n"
        "- [Action] write script\n"
        "  mkdir - Done\n"
        "  write_file - Done\n"
        "- [Action] Executing primes.py\n"
        "  run_python_file - Done"
    )


def test_normalize_section_uniform_action_prefix():
    f = pp._normalize_section
    assert f("[BA] Started: 台北市居家醫療分布分析報告") == "[Action] 台北市居家醫療分布分析報告"
    assert f("[Twinkle] Searching for X dataset.") == "[Action] Searching for X dataset."
    assert f("[Coding] Done — primes/report.pdf") == "[Action] primes/report.pdf"
    assert f("[Coding] Failed: pip timed out") == "[Action] pip timed out"
    assert f("Failed: boom") == "[Action] boom"
    assert f("plain narration") == "[Action] plain narration"
    assert f("[BA]") == "[Action]"


@pytest.mark.asyncio
async def test_panel_section_appends_and_dedupes_consecutive():
    K = "task_sec"
    await pp.panel_section(K, "u1", "telegram", K, "coding_agent",
                           "[Coding] step one")
    await pp.panel_section(K, "u1", "telegram", K, "coding_agent",
                           "[Coding] step one")  # consecutive dup → ignored
    await pp.panel_step(K, "u1", "telegram", K, "coding_agent",
                        "mkdir", "start", True)
    await pp.panel_section(K, "u1", "telegram", K, "coding_agent",
                           "[Coding] step two")
    assert pp._PANELS[K]["steps"] == [
        [pp._SEC, "[Action] step one"],
        ["mkdir", "Doing"],
        [pp._SEC, "[Action] step two"],
    ]


@pytest.mark.asyncio
async def test_section_does_not_count_as_doing_for_ticker():
    K = "task_secd"
    await pp.panel_section(K, "u1", "telegram", K, "coding_agent", "narration")
    assert pp._has_doing(pp._PANELS[K]) is False


@pytest.mark.asyncio
async def test_trim_scrolls_oldest_section_blocks(monkeypatch):
    monkeypatch.setattr(pp, "_MAX_SECTIONS", 2)
    K = "task_trim"
    for n in range(4):
        await pp.panel_section(K, "u1", "telegram", K, "coding_agent",
                               f"sec {n}")
        await pp.panel_step(K, "u1", "telegram", K, "coding_agent",
                            f"tool{n}", "start", True)
    secs = [e[1] for e in pp._PANELS[K]["steps"] if e[0] == pp._SEC]
    assert secs == ["[Action] sec 2", "[Action] sec 3"]  # oldest scrolled off


@pytest.mark.asyncio
async def test_report_step_section_routes_to_panel_section():
    from mcp_servers.tools.progress_tool import report_step
    K = "task_rsec"
    await report_step(session_id=K, step="[Coding] doing the thing",
                      status="section", channel="telegram", user_id="u1")
    assert pp._PANELS[K]["steps"] == [[pp._SEC, "[Action] doing the thing"]]


def test_render_collapses_consecutive_dups_and_counts_failures():
    state = {
        "agent_disp": "Coding Agent", "header": "Done", "phase": 0,
        "task_title": "T",
        "steps": [
            [pp._SEC, "[Action] agg"],
            ["patch_file", "Done"], ["patch_file", "Done"],
            ["patch_file", "Done"], ["patch_file", "Done"],
            ["run_python_file", "Failed"], ["run_python_file", "Failed"],
            ["run_python_file", "Done"],
        ],
    }
    out = pp._render(state)
    assert "  patch_file - Done ×4" in out
    assert "  run_python_file - Failed ×2" in out
    assert "  run_python_file - Done" in out
    assert "run_python_file - Done ×" not in out  # run==1, no suffix
    assert "2. status: Done · 2 failed (recovered)" in out


def test_render_status_failed_with_count():
    state = {"agent_disp": "BA", "header": "Failed", "phase": 0,
             "task_title": "T", "steps": [["export_pdf", "Failed"]]}
    assert "2. status: Failed · 1 failed" in pp._render(state)


def test_mono_wraps_and_escapes():
    m = pp._mono("a <b> & c")
    assert m.startswith("<pre>") and m.endswith("</pre>")
    assert "&lt;b&gt;" in m and "&amp;" in m
