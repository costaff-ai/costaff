"""`costaff agent remove` must stop the agent's containers, not just drop
its config entry.

Regression for the GA audit: the old remove left the sub-agent container
running while freeing the port in config, so the next `agent add` reused
that port and failed to bind. This mirrors `channel remove` /
`platform remove`, which already tear down containers.
"""
import pytest

import cli.commands.agent_lifecycle as mod


class _FakeRuntime:
    def __init__(self):
        self.down_calls = []
        self.removed = []

    def down(self, fragment=None, remove_orphans=True):
        self.down_calls.append((fragment, remove_orphans))

    def force_remove_container(self, name):
        self.removed.append(name)


class _FakeCore:
    name = "test-core"
    prefix = "costaff"

    def __init__(self, conf):
        self._conf = conf
        self.recreated = False

    def core_config(self):
        return self._conf

    def cn(self, s):
        return f"{self.prefix}-{s}"

    def write_config(self, conf):
        self._conf = conf

    def regen_external_agents_env(self):
        pass

    def regen_mcp_urls(self):
        pass

    def recreate_manager(self):
        self.recreated = True


@pytest.fixture
def runtime(monkeypatch):
    rt = _FakeRuntime()
    monkeypatch.setattr(mod, "runtime_for", lambda core: rt)
    return rt


def _wire(monkeypatch, conf, tmp_path=None, with_fragment=False):
    if with_fragment:
        frag = tmp_path / "compose-fragment.yaml"
        frag.write_text("services: {}\n")
        conf["external_agents"]["coding"]["fragment_path"] = str(frag)
    core = _FakeCore(conf)
    monkeypatch.setattr(mod, "_resolve_core", lambda _n: core)
    return core


def test_remove_tears_down_via_fragment(monkeypatch, runtime, tmp_path):
    conf = {"external_agents": {"coding": {
        "type": "github", "a2a_url": "http://x:1",
        "container_names": ["costaff-agent-coding", "costaff-mcp-coding"],
    }}}
    core = _wire(monkeypatch, conf, tmp_path, with_fragment=True)

    mod.agent_remove(name="coding", yes=True, core_name=None)

    # Fragment present → down() with remove_orphans=False (never nuke siblings)
    assert len(runtime.down_calls) == 1
    assert runtime.down_calls[0][1] is False
    assert "coding" not in core.core_config()["external_agents"]
    assert core.recreated is True


def test_remove_force_removes_when_no_fragment(monkeypatch, runtime):
    conf = {"external_agents": {"coding": {
        "type": "github", "a2a_url": "http://x:1",
        "container_names": ["costaff-agent-coding", "costaff-mcp-coding"],
    }}}
    core = _wire(monkeypatch, conf)

    mod.agent_remove(name="coding", yes=True, core_name=None)

    # No fragment on disk → fall back to force-removing each container
    assert runtime.removed == ["costaff-agent-coding", "costaff-mcp-coding"]
    assert "coding" not in core.core_config()["external_agents"]


def test_remove_config_entry_dropped_even_if_teardown_raises(monkeypatch):
    class _BoomRuntime:
        def down(self, **k):
            raise RuntimeError("docker daemon down")

    monkeypatch.setattr(mod, "runtime_for", lambda core: _BoomRuntime())
    conf = {"external_agents": {"coding": {
        "type": "github", "a2a_url": "http://x:1", "container_names": [],
    }}}
    core = _FakeCore(conf)
    monkeypatch.setattr(mod, "_resolve_core", lambda _n: core)

    # url-type has no fragment → down() path taken → raises → warned, not fatal
    mod.agent_remove(name="coding", yes=True, core_name=None)
    assert "coding" not in core.core_config()["external_agents"]
