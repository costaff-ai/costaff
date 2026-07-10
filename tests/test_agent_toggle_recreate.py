"""enable / disable / transfer must recreate the Manager, not just print
"restart to apply".

Regression for the GA audit: these three commands changed config.json and
regenerated the env, then told the user to `docker restart` the Manager —
but restart does NOT re-read env_file, so the change silently didn't take
effect. add/remove already recreate; these now match.
"""
import pytest
import typer

import cli.commands.agent_lifecycle as mod


class _FakeCore:
    name = "test-core"
    prefix = "costaff"

    def __init__(self, conf):
        self._conf = conf
        self.recreated = False
        self.env_regened = False

    def core_config(self):
        return self._conf

    def cn(self, s):
        return f"{self.prefix}-{s}"

    def write_config(self, conf):
        self._conf = conf

    def regen_external_agents_env(self):
        self.env_regened = True

    def recreate_manager(self):
        self.recreated = True


def _wire(monkeypatch, conf):
    core = _FakeCore(conf)
    monkeypatch.setattr(mod, "_resolve_core", lambda _n: core)
    return core


def test_enable_recreates_manager(monkeypatch):
    core = _wire(monkeypatch, {"external_agents": {"coding": {"enabled": False}}})
    mod.agent_enable(name="coding", core_name=None)
    assert core.core_config()["external_agents"]["coding"]["enabled"] is True
    assert core.env_regened and core.recreated


def test_disable_recreates_manager(monkeypatch):
    core = _wire(monkeypatch, {"external_agents": {"coding": {"enabled": True}}})
    mod.agent_disable(name="coding", core_name=None)
    assert core.core_config()["external_agents"]["coding"]["enabled"] is False
    assert core.env_regened and core.recreated


def test_transfer_enable_recreates_manager(monkeypatch):
    core = _wire(monkeypatch, {"external_agents": {"coding": {"transfer": False}}})
    # Skip the interactive confirmation gate
    monkeypatch.setattr(mod, "_confirm_enable_transfer", lambda conf, name, yes: None)
    mod.agent_transfer(name="coding", enable=True, disable=False, yes=True, core_name=None)
    assert core.core_config()["external_agents"]["coding"]["transfer"] is True
    assert core.recreated


def test_transfer_disable_recreates_manager(monkeypatch):
    core = _wire(monkeypatch, {"external_agents": {"coding": {"transfer": True}}})
    mod.agent_transfer(name="coding", enable=False, disable=True, yes=False, core_name=None)
    assert core.core_config()["external_agents"]["coding"]["transfer"] is False
    assert core.recreated


def test_transfer_noop_does_not_recreate(monkeypatch):
    """Toggling to the state it's already in exits early — no recreate."""
    core = _wire(monkeypatch, {"external_agents": {"coding": {"transfer": True}}})
    with pytest.raises(typer.Exit):
        mod.agent_transfer(name="coding", enable=True, disable=False, yes=True, core_name=None)
    assert not core.recreated
