"""services/agent_components — shared per-agent MCP/skill semantics
(consumed by both the dashboard routers and the costaff CLI)."""
import pytest

from services.agent_components import (
    agent_card_url,
    agent_mcp_map,
    available_mcps,
    set_agent_mcps,
)


CONF = {
    "mcp": ["costaff"],
    "external_mcp": {
        "notion": {"url": "http://n:1", "enabled": True},
        "disabled-one": {"url": "http://d:1", "enabled": False},
    },
    "external_agents": {
        "coding": {"type": "github", "public_port": 18110,
                   "fragment_path": "/tmp/frag.yaml", "container_names": ["costaff-agent-coding"]},
        "notion-agent": {"type": "url", "a2a_url": "http://notion-agent:8080"},
    },
    "agent_mcps": {"coding": ["costaff"]},
}


class _FakeCore:
    name = "test"
    compose_project = ""
    compose_file = ""
    env_path = "/tmp/.env"

    def __init__(self, conf):
        self._conf = conf
        self.regens = 0
        self.manager_recreates = 0

    def core_config(self):
        return self._conf

    def write_config(self, conf):
        self._conf = conf

    def regen_mcp_urls(self):
        self.regens += 1

    def recreate_manager(self):
        self.manager_recreates += 1


def test_available_mcps_skips_disabled():
    assert available_mcps(CONF) == ["costaff", "notion"]


def test_agent_mcp_map_shape():
    m = agent_mcp_map(CONF)
    assert m["available_mcps"] == ["costaff", "notion"]
    assert m["agent_mcps"]["costaff_agent"] == ["costaff", "notion"]  # unset → all
    assert m["agent_mcps"]["coding"] == ["costaff"]                   # explicit
    assert "notion_agent" not in m["agent_mcps"]                      # url agents not managed


def test_set_agent_mcps_writes_and_regens():
    core = _FakeCore(dict(CONF, agent_mcps={}))
    restart = set_agent_mcps(core, "costaff_agent", ["costaff"])
    assert core.core_config()["agent_mcps"]["costaff_agent"] == ["costaff"]
    assert core.regens == 1
    restart()
    assert core.manager_recreates == 1  # manager restart path


def test_set_agent_mcps_github_agent_gets_compose_restart():
    core = _FakeCore(dict(CONF))
    restart = set_agent_mcps(core, "coding", ["costaff", "notion"])
    assert callable(restart) and restart is not core.recreate_manager


def test_set_agent_mcps_unknown_agent_without_fragment_returns_none():
    core = _FakeCore(dict(CONF))
    assert set_agent_mcps(core, "notion_agent", ["costaff"]) is None


def test_set_agent_mcps_rejects_unknown_mcp():
    core = _FakeCore(dict(CONF))
    with pytest.raises(ValueError, match="unknown MCP"):
        set_agent_mcps(core, "coding", ["nope"])


def test_agent_card_url_resolution():
    assert agent_card_url({"type": "github", "public_port": 18110}) == "http://localhost:18110"
    assert agent_card_url({"type": "url", "a2a_url": "http://x:8080"}) == "http://x:8080"
    assert agent_card_url({"type": "github"}) is None
