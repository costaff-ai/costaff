"""Sub-agent loader: read EXTERNAL_AGENTS_CONFIG and register external A2A agents.

Usage:
    from .sub_agents import load_all_sub_agents
    sub_agents = load_all_sub_agents()  # list of RemoteA2aAgent, ready for LlmAgent(sub_agents=...)

Each entry in EXTERNAL_AGENTS_CONFIG must provide an `a2a_url` and may
provide a `description`. Hyphens in agent names are normalized to
underscores to match ADK's agent_name convention.

ADK auto-injects each sub-agent's name + description into the
transfer_to_agent tool spec, so manual roster rendering in the system
prompt is not required.
"""
import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def load_all_sub_agents() -> List:
    """Read EXTERNAL_AGENTS_CONFIG and build a list of RemoteA2aAgent.

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
    except ImportError as e:
        logger.error(f"A2A imports unavailable: {e}")
        return []

    try:
        agents_config = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"EXTERNAL_AGENTS_CONFIG is not valid JSON: {e}")
        return []

    sub_agents = []
    for agent_name, agent_cfg in agents_config.items():
        a2a_url = agent_cfg.get("a2a_url", "").strip()
        description = agent_cfg.get("description", f"Specialist: {agent_name}").strip()

        if not a2a_url:
            continue

        try:
            a2a_name = agent_name.replace("-", "_")
            logger.info(f"Registering sub-agent '{a2a_name}' via A2A at {a2a_url}")

            sub_agents.append(RemoteA2aAgent(
                name=a2a_name,
                description=description,
                agent_card=f"{a2a_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}",
                use_legacy=False,
            ))
            logger.info(f"Successfully registered sub-agent '{a2a_name}'")
        except Exception as e:
            logger.error(f"Failed to load sub-agent '{agent_name}': {e}")

    return sub_agents
