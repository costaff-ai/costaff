import logging
import os
import re
import threading

import httpx
from fastapi import APIRouter, HTTPException, Depends

from services.auth import AuthManager
from services.audit import audit
from services.config import ConfigManager
from services.docker import DockerManager
from server.schemas import ExternalAgentAddRequest, ExternalAgentUpdateRequest
from utils.helpers import _validate_a2a_url

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/agents")
def get_available_agents(auth: bool = Depends(AuthManager.verify_token)):
    try:
        with httpx.Client(timeout=5.0) as client:
            return client.get(f"http://localhost:{os.getenv('COSTAFF_AGENT_PORT', '18080')}/list-apps").json()
    except Exception:
        return []


@router.get("/api/external-agents")
def list_external_agents(auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    result = []
    for name, agent in conf.get("external_agents", {}).items():
        # Skip legacy migrated entries that have no public_port (old compose-managed costaff-agent-coding)
        if agent.get("type") == "github" and not agent.get("public_port"):
            continue
        health = False
        if agent.get("enabled"):
            # GitHub agents: use localhost:<public_port> (Docker internal URL not reachable from host)
            # URL agents: use a2a_url directly
            health_url = None
            if agent.get("type") == "github" and agent.get("public_port"):
                health_url = f"http://localhost:{agent['public_port']}/.well-known/agent-card.json"
            elif agent.get("type") == "url" and agent.get("a2a_url"):
                health_url = f"{agent['a2a_url']}/.well-known/agent-card.json"
            if health_url:
                try:
                    with httpx.Client(timeout=3.0) as client:
                        r = client.get(health_url)
                        health = r.status_code == 200
                except Exception:
                    pass
        result.append({
            "name": name,
            "type": agent.get("type", "url"),
            "a2a_url": agent.get("a2a_url", ""),
            "description": agent.get("description", ""),
            "enabled": agent.get("enabled", True),
            "mcp_configurable": agent.get("mcp_configurable", False),
            "health": health,
            "version": agent.get("version"),
            "container_names": agent.get("container_names", []),
        })
    return result


@router.post("/api/external-agents")
def add_external_agent(req: ExternalAgentAddRequest, auth: bool = Depends(AuthManager.verify_token)):
    name = req.name.strip().lower().replace(" ", "-")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', name):
        raise HTTPException(400, "Agent name must be lowercase alphanumeric with hyphens/underscores.")
    try:
        _validate_a2a_url(req.a2a_url)
    except ValueError as e:
        raise HTTPException(400, f"Invalid a2a_url: {e}")
    conf = ConfigManager.get_config()
    if name in conf.get("external_agents", {}):
        raise HTTPException(400, f"Agent '{name}' already exists.")
    conf.setdefault("external_agents", {})[name] = {
        "type": "url",
        "a2a_url": req.a2a_url,
        "description": req.description or "",
        "enabled": True,
    }
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    threading.Thread(target=DockerManager.run_action, args=("costaff-agent-costaff", "restart"), daemon=True).start()
    audit("agent.add", name=name, url=req.a2a_url)
    return {"status": "ok", "name": name}


@router.patch("/api/external-agents/{name}")
def update_external_agent(name: str, req: ExternalAgentUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        raise HTTPException(404, f"Agent '{name}' not found.")
    agent = conf["external_agents"][name]
    if req.a2a_url is not None:
        try:
            _validate_a2a_url(req.a2a_url)
        except ValueError as e:
            raise HTTPException(400, f"Invalid a2a_url: {e}")
        agent["a2a_url"] = req.a2a_url
    if req.description is not None:
        agent["description"] = req.description
    if req.enabled is not None:
        agent["enabled"] = req.enabled
        if name == "costaff-agent-coding":
            conf["coding_agent_enabled"] = req.enabled
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    threading.Thread(target=DockerManager.run_action, args=("costaff-agent-costaff", "restart"), daemon=True).start()
    audit("agent.update", name=name, changes={k: v for k, v in req.dict(exclude_unset=True).items()})
    return {"status": "ok"}


@router.delete("/api/external-agents/{name}")
def remove_external_agent(name: str, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        raise HTTPException(404, f"Agent '{name}' not found.")
    if conf["external_agents"][name].get("type") == "github":
        raise HTTPException(400, "GitHub-deployed agents must be removed via CLI: costaff agent remove")
    del conf["external_agents"][name]
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    threading.Thread(target=DockerManager.run_action, args=("costaff-agent-costaff", "restart"), daemon=True).start()
    audit("agent.delete", name=name)
    return {"status": "ok"}


@router.get("/api/dashboard/ai-team")
def dashboard_ai_team(auth: bool = Depends(AuthManager.verify_token)):
    """Returns active regular works with their last execution output + recent diary entries."""
    from sqlalchemy import text
    from services.database import DatabaseManager
    from utils.helpers import _serialize_row

    engine = DatabaseManager.get_engine()
    if not engine:
        return {"works": [], "diary": []}
    try:
        with engine.connect() as conn:
            # Active regular works with last log output
            works_res = conn.execute(text(
                "SELECT id, title, cron, agent_id, channel, recipient, status, last_run "
                "FROM regular_works ORDER BY created_at ASC"
            ))
            works = []
            for r in works_res:
                w = _serialize_row(dict(r._mapping))
                # Attach last successful log output
                log = conn.execute(text(
                    "SELECT output, status, created_at FROM regular_work_logs "
                    "WHERE regular_work_id = :id ORDER BY created_at DESC LIMIT 1"
                ), {"id": w["id"]}).fetchone()
                w["last_output"] = log[0] if log else None
                w["last_status"] = log[1] if log else None
                w["last_ran_at"] = _serialize_row({"t": log[2]})["t"] if log else None
                works.append(w)

            # Recent diary entries
            diary_res = conn.execute(text(
                "SELECT id, agent_name, date, type, done, blocker, next, created_at "
                "FROM diary ORDER BY date DESC, created_at DESC LIMIT 20"
            ))
            diary = [_serialize_row(dict(r._mapping)) for r in diary_res]

        return {"works": works, "diary": diary}
    except Exception:
        logger.exception("dashboard ai-team error")
        return {"works": [], "diary": []}
