"""Remote A2A agent loader: wraps each registered remote agent as an AgentTool.

Why AgentTool, not sub_agents=[...]:
    The older `sub_agents=[RemoteA2aAgent(...)]` + `transfer_to_agent`
    mechanism packs the manager's full session history (including the
    user's "OK" confirmation turn) and sends it to the sub-agent. The
    sub-agent's LLM then sees "OK" as the latest user content and replies
    conversationally without invoking any tool — silently breaking the run.

    `AgentTool` instead wraps each remote agent as a callable function
    `agent_name(request: str)`. The manager LLM is forced to write a
    self-contained, imperative task description; the sub-agent receives
    only that string as a clean Content(role='user', parts=[text=request]).
    No replayed history, no "[manager] said:" prefixes — sub-agent acts.

    Reference: ADK official multi-agent docs distinguish:
    - AgentTool (tools=[...]): explicit, controlled, synchronous
    - transfer_to_agent (sub_agents=[...]): dynamic, LLM-driven, context-switching

Usage:
    from .sub_agents import load_all_remote_agent_tools
    tools.extend(load_all_remote_agent_tools())   # add to LlmAgent(tools=[...])

The manager's `LlmAgent(sub_agents=[...])` should remain `[]`. Each tool's
description is taken from the agent card's description field, so the
manager LLM can route tasks based on registered agents' self-declarations.

Scalability note (10+ agents):
    `load_all_remote_agent_tools` returns one AgentTool per registered
    remote agent. ADK's function-calling spec for each tool consumes
    ~80-150 tokens. With 50+ agents this becomes prompt pressure; at
    that point introduce a registry/dispatcher tier (see
    `skill/costaff-agent/A2A_SERVER_SKILL.md`). For the current scale
    (<10 agents), direct tool wiring is the right choice.
"""
import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def load_all_remote_agent_tools() -> List:
    """Read EXTERNAL_AGENTS_CONFIG and wrap each remote agent in AgentTool.

    Returns an empty list when the env var is unset, malformed, or no
    entry has a usable `a2a_url`. Individual registration failures are
    logged but don't block the rest.
    """
    raw = os.getenv("EXTERNAL_AGENTS_CONFIG", "").strip()
    if not raw:
        return []

    try:
        from google.adk.agents.remote_a2a_agent import (
            RemoteA2aAgent,
            AGENT_CARD_WELL_KNOWN_PATH,
        )
        from google.adk.tools.agent_tool import AgentTool
    except ImportError as e:
        logger.error(f"ADK A2A / AgentTool imports unavailable: {e}")
        return []

    try:
        agents_config = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"EXTERNAL_AGENTS_CONFIG is not valid JSON: {e}")
        return []

    agent_tools = []
    for agent_name, agent_cfg in agents_config.items():
        a2a_url = agent_cfg.get("a2a_url", "").strip()
        description = agent_cfg.get("description", f"Specialist: {agent_name}").strip()

        if not a2a_url:
            continue

        try:
            a2a_name = agent_name.replace("-", "_")
            logger.info(f"Wrapping remote agent '{a2a_name}' as AgentTool: {a2a_url}")
            remote = RemoteA2aAgent(
                name=a2a_name,
                description=description,
                agent_card=f"{a2a_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}",
                use_legacy=False,
            )
            agent_tools.append(AgentTool(agent=remote))
            logger.info(f"Successfully registered AgentTool for '{a2a_name}'")
        except Exception:
            logger.exception("Failed to wrap remote agent '%s' as AgentTool", agent_name)

    return agent_tools
