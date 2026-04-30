"""Tests for agents.costaff_agent.sub_agents.load_all_remote_agent_tools.

This is a regression guard for the AgentTool migration: the manager must wrap
each remote agent in `AgentTool(agent=RemoteA2aAgent(...))` so the manager
LLM gets a callable function with an explicit `request: str` parameter.
Reverting to bare `RemoteA2aAgent` (the older `sub_agents=[...]` pattern)
would silently break multi-turn flows where the user's "OK" confirmation
gets packaged as the sub-agent's last user content.
"""
import importlib.util
import json
from pathlib import Path

import pytest

# Load the module from its file path to bypass the package __init__.py,
# which would eagerly construct the full LlmAgent and require model env vars.
_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents" / "costaff_agent" / "sub_agents" / "__init__.py"
)


def _load_sub_agents_module():
    spec = importlib.util.spec_from_file_location("_sub_agents_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sub_agents_module():
    return _load_sub_agents_module()


@pytest.fixture
def agent_tool_class():
    from google.adk.tools.agent_tool import AgentTool
    return AgentTool


@pytest.fixture
def remote_a2a_class():
    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
    return RemoteA2aAgent


def test_returns_empty_list_when_env_unset(monkeypatch, sub_agents_module):
    monkeypatch.delenv("EXTERNAL_AGENTS_CONFIG", raising=False)
    assert sub_agents_module.load_all_remote_agent_tools() == []


def test_returns_empty_list_when_env_blank(monkeypatch, sub_agents_module):
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", "   ")
    assert sub_agents_module.load_all_remote_agent_tools() == []


def test_returns_empty_list_on_malformed_json(monkeypatch, sub_agents_module):
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", "{not json}")
    assert sub_agents_module.load_all_remote_agent_tools() == []


def test_skips_entries_without_a2a_url(monkeypatch, sub_agents_module):
    cfg = {
        "valid": {"a2a_url": "http://valid:8081", "description": "ok"},
        "missing": {"description": "no url"},
        "blank": {"a2a_url": "", "description": "blank url"},
    }
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert len(tools) == 1
    assert tools[0].agent.name == "valid"


def test_returns_agent_tool_not_remote_a2a_agent(
    monkeypatch, sub_agents_module, agent_tool_class, remote_a2a_class
):
    """The critical regression guard: tools must be AgentTool, not bare
    RemoteA2aAgent. If this assertion ever fails, multi-turn confirmation
    flows will silently break — the manager LLM will see `transfer_to_agent`
    instead of `<name>(request=str)` and sub-agents will receive packed
    session history including stray "OK" turns."""
    cfg = {"coding": {"a2a_url": "http://costaff-agent-coding:8081", "description": "Coding"}}
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert len(tools) == 1
    assert isinstance(tools[0], agent_tool_class), (
        f"Expected AgentTool, got {type(tools[0]).__name__}. "
        "If this fails, the manager has reverted to the broken sub_agents pattern."
    )
    assert isinstance(tools[0].agent, remote_a2a_class)


def test_normalizes_hyphens_to_underscores_in_agent_name(monkeypatch, sub_agents_module):
    """ADK requires identifier-safe names. The config key may use hyphens
    (e.g. `business-analysis`) but the registered tool name must be
    `business_analysis`."""
    cfg = {"business-analysis": {"a2a_url": "http://ba:8081", "description": "BA"}}
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert tools[0].agent.name == "business_analysis"


def test_uses_description_from_config(monkeypatch, sub_agents_module):
    """Description is what the manager LLM sees in its tool spec — it
    drives routing decisions. Each agent's description must come straight
    from EXTERNAL_AGENTS_CONFIG verbatim."""
    cfg = {"coding": {"a2a_url": "http://x:1", "description": "Python expert with sandbox"}}
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert tools[0].agent.description == "Python expert with sandbox"


def test_falls_back_to_default_description_when_missing(monkeypatch, sub_agents_module):
    cfg = {"coding": {"a2a_url": "http://x:1"}}
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert "coding" in tools[0].agent.description.lower()


def test_agent_card_url_uses_well_known_path(monkeypatch, sub_agents_module):
    """RemoteA2aAgent fetches /.well-known/agent-card.json. The URL we
    construct must include that suffix or the A2A handshake fails."""
    cfg = {"coding": {"a2a_url": "http://x:1", "description": "d"}}
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    card = tools[0].agent._agent_card_source
    assert card.endswith(".well-known/agent-card.json"), card


def test_handles_multiple_agents(monkeypatch, sub_agents_module, agent_tool_class):
    cfg = {
        "coding": {"a2a_url": "http://c:1", "description": "code"},
        "business-analysis": {"a2a_url": "http://b:1", "description": "report"},
        "database": {"a2a_url": "http://d:1", "description": "sql"},
    }
    monkeypatch.setenv("EXTERNAL_AGENTS_CONFIG", json.dumps(cfg))
    tools = sub_agents_module.load_all_remote_agent_tools()
    assert len(tools) == 3
    assert all(isinstance(t, agent_tool_class) for t in tools)
    names = sorted(t.agent.name for t in tools)
    assert names == ["business_analysis", "coding", "database"]
