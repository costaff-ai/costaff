"""Per-agent component wiring (MCP assignment, A2A skills) — shared by the
dashboard routers and the `costaff agent mcp` / `costaff agent skills` CLI so
both surfaces speak the exact same semantics.

Component model (mirrors the dashboard's per-agent cards):
- ``agent_mcps``  : config map  agent_id → [mcp server names]. Missing key
                    means "all available MCPs" (the historical default).
- MCP consumers   : the manager (``costaff_agent``) and github-type external
                    agents (URL agents run elsewhere and manage their own).
- Skills          : an external agent's A2A card is the source of truth.
"""
import os
import subprocess

import httpx


# --- MCP assignment ---------------------------------------------------------

def available_mcps(conf: dict) -> list:
    """Built-in MCP names + enabled external extensions."""
    names = list(conf.get("mcp", []))
    for name, val in conf.get("external_mcp", {}).items():
        enabled = val.get("enabled", True) if isinstance(val, dict) else True
        if enabled:
            names.append(name)
    return names


def agent_mcp_map(conf: dict) -> dict:
    """Same shape as the dashboard's GET /api/agent-mcp-config."""
    all_names = available_mcps(conf)
    agent_mcps = conf.get("agent_mcps", {})
    result = {"costaff_agent": agent_mcps.get("costaff_agent", all_names)}
    for name, agent in conf.get("external_agents", {}).items():
        if agent.get("type") == "github":
            key = name.replace("-", "_")
            result[key] = agent_mcps.get(key, all_names)
    return {"available_mcps": all_names, "agent_mcps": result}


def set_agent_mcps(core, agent_id: str, mcps: list):
    """Assign the MCP set for one agent on this core (UI POST semantics).

    Writes ``agent_mcps``, regenerates the MCP URL env vars, and returns a
    zero-arg restart callable for the affected container (or ``None`` when
    nothing needs recreating). The dashboard runs the callable in a thread;
    the CLI runs it synchronously.
    """
    conf = core.core_config()
    known = set(available_mcps(conf))
    unknown = [m for m in mcps if m not in known]
    if unknown:
        raise ValueError(f"unknown MCP name(s): {', '.join(unknown)} (available: {', '.join(sorted(known))})")

    conf.setdefault("agent_mcps", {})[agent_id] = list(mcps)
    core.write_config(conf)
    core.regen_mcp_urls()
    return _restart_for(core, conf, agent_id)


def _restart_for(core, conf: dict, agent_id: str):
    """Restart callable for the container that consumes agent_id's MCP env."""
    if agent_id == "costaff_agent":
        return core.recreate_manager

    agent_id_to_name = {n.replace("-", "_"): n for n in conf.get("external_agents", {})}
    ext_name = agent_id_to_name.get(agent_id)
    ext = conf.get("external_agents", {}).get(ext_name) if ext_name else None
    if not (ext and ext.get("type") == "github" and ext.get("fragment_path")):
        return None

    fragment_path = ext["fragment_path"]
    primary_service = ext.get("container_names", [ext_name])[0]

    def _recreate():
        from dotenv import load_dotenv
        from services.docker import DockerManager
        from utils.paths import _project_root

        load_dotenv(core.env_path, override=True)
        base = DockerManager.get_cmd()
        if core.compose_project:
            base += ["-p", core.compose_project]
        if core.compose_file:
            base += ["-f", core.compose_file]
        base += ["-f", fragment_path]
        cwd = os.path.dirname(core.compose_file) if core.compose_file else _project_root
        subprocess.run(base + ["up", "-d", "--force-recreate", "--no-deps", primary_service],
                       check=False, cwd=cwd)

    return _recreate


# --- A2A skills --------------------------------------------------------------

def agent_card_url(agent: dict):
    """Host-side reachable card base URL (same resolution as the dashboard)."""
    if agent.get("type") == "github" and agent.get("public_port"):
        return f"http://localhost:{agent['public_port']}"
    if agent.get("type") == "url" and agent.get("a2a_url"):
        return agent["a2a_url"]
    return None


def fetch_agent_card(agent: dict, timeout: float = 5.0) -> dict:
    """Fetch an external agent's live A2A card. Raises RuntimeError on failure."""
    base = agent_card_url(agent)
    if not base:
        raise RuntimeError("agent has no reachable A2A endpoint")
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{base}/.well-known/agent-card.json")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise RuntimeError(f"could not fetch agent card: {e}") from e
