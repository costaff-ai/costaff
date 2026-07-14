"""Tests for `costaff update --all` plugin fan-out (feature #1)."""
import typer

from cli.commands import update as upd


def _patch(monkeypatch, conf, agent_fn, channel_fn):
    monkeypatch.setattr(
        "services.config.ConfigManager.get_config", staticmethod(lambda: conf)
    )
    monkeypatch.setattr("cli.commands.agent_container.agent_rebuild", agent_fn)
    monkeypatch.setattr("cli.commands.channel.channel_rebuild", channel_fn)


def test_update_all_rebuilds_source_plugins_and_skips_remote(monkeypatch):
    conf = {
        "external_agents": {
            "coding": {"type": "github", "fragment_path": "/f", "container_names": ["c"]},
            "remote": {"type": "url", "a2a_url": "http://x"},  # not pinnable
        },
        "dynamic_channels": {
            "telegram": {"fragment_path": "/f2", "container_names": ["t"]},
        },
    }
    calls = []
    _patch(
        monkeypatch,
        conf,
        lambda **kw: calls.append(("agent", kw)),
        lambda **kw: calls.append(("channel", kw)),
    )

    upd._update_all_plugins("v0.1.0-alpha-2")

    assert [c[0] for c in calls] == ["agent", "channel"]  # remote url skipped
    assert calls[0][1]["name"] == "coding"
    assert calls[0][1]["tag"] == "v0.1.0-alpha-2"
    assert calls[1][1]["name"] == "telegram"
    # Regression: core_name MUST be passed explicitly as None — otherwise the
    # rebuild funcs receive the Typer OptionInfo sentinel and every rebuild
    # dies in _resolve_core, silently making `update --all` a no-op.
    assert calls[0][1]["core_name"] is None
    assert calls[1][1]["core_name"] is None


def test_resolve_core_tolerates_option_info_sentinel():
    """Calling a command func directly (as update --all does) passes the
    OptionInfo default, not None. _resolve_core must treat it as unset."""
    from cli.commands.agent_lifecycle import _resolve_core, CORE_OPT
    core = _resolve_core(CORE_OPT)  # must NOT raise typer.Exit
    assert core.name  # resolves to a real (active/default) core


def test_update_all_continues_after_one_failure(monkeypatch):
    conf = {
        "external_agents": {
            "coding": {"type": "github", "fragment_path": "/f", "container_names": ["c"]},
        },
        "dynamic_channels": {
            "telegram": {"fragment_path": "/f2", "container_names": ["t"]},
        },
    }
    channel_calls = []

    def failing_agent(**kw):
        raise typer.Exit(1)

    _patch(
        monkeypatch,
        conf,
        failing_agent,
        lambda **kw: channel_calls.append(kw),
    )

    # Must not raise — one plugin failing should not abort the batch.
    upd._update_all_plugins("v9")
    assert len(channel_calls) == 1
    assert channel_calls[0]["name"] == "telegram"


def test_update_all_no_plugins_is_noop(monkeypatch):
    _patch(
        monkeypatch,
        {"external_agents": {}, "dynamic_channels": {}},
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    upd._update_all_plugins(None)  # no plugins → clean no-op


# ---------------------------------------------------------------------------
# _core_images_changed — detect updates that need a rebuild, not a restart
# ---------------------------------------------------------------------------

def test_core_images_changed_flags_migrations_and_mcp(monkeypatch):
    def fake_run(cmd, **kw):
        class R:
            stdout = (
                "migrations/versions/0003_x.py\n"
                "mcp_servers/executors/project_task.py\n"
                "server/routers/agents.py\n"   # host-side — must be ignored
                "frontend/js/app.js\n"          # host-side — must be ignored
            )
        return R()
    monkeypatch.setattr(upd.subprocess, "run", fake_run)
    changed = upd._core_images_changed("aaa", "bbb")
    assert "migrations/versions/0003_x.py" in changed
    assert "mcp_servers/executors/project_task.py" in changed
    assert not any(f.startswith(("server/", "frontend/")) for f in changed)


def test_core_images_changed_flags_core_package(monkeypatch):
    # core/ AND services/ are baked into costaff-mcp-costaff (Dockerfile
    # COPY . .) and used at container runtime: core/notifiers/webchat.py is
    # beta-3's push-sender case, services/config.py is imported by
    # mcp_servers/tools/_shared.py (license usage gate). Changes there need a
    # rebuild, not just a restart. cli/ is host-side (applied by the CLI
    # reinstall) and must stay ignored.
    def fake_run(cmd, **kw):
        class R:
            stdout = (
                "core/notifiers/webchat.py\n"
                "services/config.py\n"       # in-image — must be flagged
                "cli/commands/channel.py\n"  # host-side — must be ignored
            )
        return R()
    monkeypatch.setattr(upd.subprocess, "run", fake_run)
    changed = upd._core_images_changed("aaa", "bbb")
    assert "core/notifiers/webchat.py" in changed
    assert "services/config.py" in changed
    assert not any(f.startswith("cli/") for f in changed)


def test_core_images_changed_empty_when_no_core_paths(monkeypatch):
    def fake_run(cmd, **kw):
        class R:
            stdout = "cli/commands/update.py\nfrontend/index.html\n"
        return R()
    monkeypatch.setattr(upd.subprocess, "run", fake_run)
    assert upd._core_images_changed("aaa", "bbb") == []


def test_core_images_changed_noop_when_rev_unchanged(monkeypatch):
    # Same rev (or missing rev) → never shells out to git diff
    def boom(*a, **k):
        raise AssertionError("git diff should not run")
    monkeypatch.setattr(upd.subprocess, "run", boom)
    assert upd._core_images_changed("aaa", "aaa") == []
    assert upd._core_images_changed("", "bbb") == []
