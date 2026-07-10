"""agent add/remove must keep the manager's MCP wiring consistent.

- add (mcp_configurable): registers the agent's own MCP in `mcp` and
  `agent_mcps[<key>]`, seeds the tool whitelist, but must NOT append the
  agent to `agent_mcps.costaff_agent` — the manager reaches specialists via
  A2A, and extra MCPs on the manager trigger the ADK anyio race.
- remove: tears down all four places add wrote (`mcp`, `agent_mcps[<key>]`,
  a stale entry in `agent_mcps.costaff_agent`, `agent_mcp_filters[<key>]`),
  so no dead `<prefix>-mcp-<name>` URL is regenerated into the manager env.
"""
import pytest

import cli.commands.agent_lifecycle as mod


class _Core:
    name = "test"
    label = "Test"
    prefix = "costaff"
    base_dir = "/tmp"
    is_default = True

    def __init__(self, conf):
        self._conf = conf
        self.regen_mcp = 0

    def core_config(self):
        return self._conf

    def cn(self, s):
        return f"{self.prefix}-{s}"

    def write_config(self, conf):
        self._conf = conf

    def regen_external_agents_env(self):
        pass

    def regen_mcp_urls(self):
        self.regen_mcp += 1

    def recreate_manager(self):
        pass


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

def test_add_does_not_put_child_mcp_on_manager(monkeypatch):
    core = _Core({"external_agents": {}})
    monkeypatch.setattr(mod, "_resolve_core", lambda n: core)
    # No real license / deploy: mock them out.
    monkeypatch.setattr("core.license.LicenseManager.load", classmethod(lambda cls: None))
    monkeypatch.setattr("core.license.LicenseManager.check_agent_limit", classmethod(lambda cls, n: None))
    monkeypatch.setattr(mod, "_deploy_local_agent", lambda *a, **k: {
        "type": "github", "a2a_url": "http://coding:8081", "enabled": True,
        "mcp_configurable": True, "container_names": ["costaff-agent-coding"],
    })

    mod.agent_add(name="coding", url=None, local="/src", github=None, tag=None,
                  env=None, description="", strict=False, enable_transfer=False,
                  yes=True, core_name=None)

    conf = core.core_config()
    # The manager stays on its own MCP only — invariant preserved
    assert conf["agent_mcps"]["costaff_agent"] == ["costaff"]
    # But the agent's own wiring IS registered
    assert "coding" in conf["mcp"]
    assert conf["agent_mcps"]["coding"] == ["costaff", "coding"]
    assert "coding" in conf["agent_mcp_filters"]


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def test_remove_cleans_all_mcp_wiring(monkeypatch):
    # Start from the state add produces, PLUS a stale costaff_agent entry as an
    # older buggy add would have left — remove must clean everything.
    conf = {
        "external_agents": {"coding": {"type": "github", "container_names": []}},
        "mcp": ["costaff", "coding"],
        "agent_mcps": {"costaff_agent": ["costaff", "coding"], "coding": ["costaff", "coding"]},
        "agent_mcp_filters": {"coding": {"costaff": ["send_message_now"]}},
    }
    core = _Core(conf)
    monkeypatch.setattr(mod, "_resolve_core", lambda n: core)

    class _Rt:
        def down(self, **k):
            pass
        def force_remove_container(self, n):
            pass
    monkeypatch.setattr(mod, "runtime_for", lambda c: _Rt())

    mod.agent_remove(name="coding", yes=True, core_name=None)

    out = core.core_config()
    assert "coding" not in out["mcp"]
    assert "coding" not in out["agent_mcps"]
    assert "coding" not in out["agent_mcps"]["costaff_agent"]  # stale entry purged
    assert "coding" not in out["agent_mcp_filters"]
    assert core.regen_mcp >= 1  # env regenerated so the dead URL is dropped


def test_remove_is_safe_when_no_mcp_wiring(monkeypatch):
    # url-type agent never had MCP wiring — remove must not KeyError.
    conf = {"external_agents": {"remote": {"type": "url", "container_names": []}}}
    core = _Core(conf)
    monkeypatch.setattr(mod, "_resolve_core", lambda n: core)

    class _Rt:
        def down(self, **k):
            pass
        def force_remove_container(self, n):
            pass
    monkeypatch.setattr(mod, "runtime_for", lambda c: _Rt())

    mod.agent_remove(name="remote", yes=True, core_name=None)
    assert "remote" not in core.core_config()["external_agents"]
