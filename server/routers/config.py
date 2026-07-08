import os
import json
import subprocess
import threading

from fastapi import APIRouter, HTTPException, Depends, Request
from dotenv import load_dotenv, set_key

from services.auth import AuthManager
from services.config import ConfigManager
from services.cores import active_core
from services.docker import DockerManager
from server.schemas import GatewayUpdateRequest, AddMCPRequest, AgentMCPConfigRequest
from utils.paths import PATHS, _project_root, _runtime_root

router = APIRouter()


@router.get("/api/config")
def get_api_config(auth: bool = Depends(AuthManager.verify_token)):
    conf = active_core().core_config()  # active core's external_mcp / channels / agent_mcps
    load_dotenv(PATHS["env"])
    # Sync environment tokens to the config object for UI
    if "gateways_config" not in conf:
        conf["gateways_config"] = {}
    tokens = {"tg": "TELEGRAM_BOT_TOKEN", "dc": "DISCORD_BOT_TOKEN", "line": "LINE_CHANNEL_ACCESS_TOKEN"}
    for k, v in tokens.items():
        if t := os.getenv(v):
            conf["gateways_config"].setdefault(k, {})["token"] = t
    return conf


@router.post("/api/config/costaff-agent-coding")
def set_coding_agent(req: dict, auth: bool = Depends(AuthManager.verify_token)):
    core = active_core()
    conf = core.core_config()
    enabled_changed = "enabled" in req
    if enabled_changed:
        enabled = bool(req["enabled"])
        conf["coding_agent_enabled"] = enabled
        # Keep external_agents in sync
        coding_a2a_url = os.getenv("CODING_A2A_INTERNAL_URL", "http://costaff-agent-coding:8081")
        conf.setdefault("external_agents", {}).setdefault("costaff-agent-coding", {
            "type": "github",
            "a2a_url": coding_a2a_url,
            "description": "Writes and runs code to solve problems involving computation, data processing, or program logic. Returns execution results and generated file paths.",
            "container_names": ["costaff-agent-coding", "costaff-mcp-coding"],
        })["enabled"] = enabled
        conf["external_agents"]["costaff-agent-coding"]["a2a_url"] = coding_a2a_url
    core.write_config(conf)
    core.regen_external_agents_env()

    return {"status": "ok", "coding_agent_enabled": conf["coding_agent_enabled"]}


@router.post("/api/gateways")
def save_gateway(req: GatewayUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    token_env_map = {"tg": "TELEGRAM_BOT_TOKEN", "dc": "DISCORD_BOT_TOKEN", "line": "LINE_CHANNEL_ACCESS_TOKEN"}
    secret_env_map = {"line": "LINE_CHANNEL_SECRET"}
    p = req.platform
    if p not in token_env_map:
        raise HTTPException(status_code=400, detail="Unknown platform.")
    # Save token to the active core's .env
    core = active_core()
    if token := req.config.get("token"):
        set_key(core.env_path, token_env_map[p], token)
    if secret := req.config.get("secret"):
        if p in secret_env_map:
            set_key(core.env_path, secret_env_map[p], secret)
    # Add to channels if not already present
    conf = core.core_config()
    if p not in conf.get("channels", []):
        conf.setdefault("channels", []).append(p)
    core.write_config(conf)
    return {"status": "ok"}


@router.post("/api/mcp")
def add_mcp(req: AddMCPRequest, auth: bool = Depends(AuthManager.verify_token)):
    core = active_core()
    conf = core.core_config()
    if req.is_external:
        # Accept Dive-format object or legacy plain URL string
        if req.config and isinstance(req.config, dict) and "url" in req.config:
            dive_obj = {
                "url":       req.config.get("url", req.url or ""),
                "transport": req.config.get("transport", "streamable"),
                "enabled":   req.config.get("enabled", True),
                "headers":   req.config.get("headers", {}),
            }
            if not dive_obj["url"]:
                raise HTTPException(status_code=400, detail="External URL missing.")
            conf["external_mcp"][req.name] = dive_obj
        else:
            url = req.url
            if not url:
                raise HTTPException(status_code=400, detail="External URL missing.")
            conf["external_mcp"][req.name] = {
                "url":       url,
                "transport": "sse" if "/mcp" in url else "streamable",
                "enabled":   True,
                "headers":   {},
            }
        if req.name in conf["mcp"]:
            conf["mcp"].remove(req.name)
    else:
        if req.name not in conf["mcp"]:
            conf["mcp"].append(req.name)
        if req.name in conf["external_mcp"]:
            del conf["external_mcp"][req.name]

    core.write_config(conf)
    if req.config and req.name == "costaff":
        path = os.path.join("mcp_servers", "costaff", "server.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(req.config, f, indent=2)

    core.regen_mcp_urls()
    return {"status": "success"}


@router.get("/api/mcp/{name}/config")
def get_mcp_config(name: str, auth: bool = Depends(AuthManager.verify_token)):
    conf = active_core().core_config()
    # External MCP: return Dive-format object
    if name in conf.get("external_mcp", {}):
        val = conf["external_mcp"][name]
        if isinstance(val, str):
            return {"url": val, "transport": "sse" if "/mcp" in val else "streamable", "enabled": True, "headers": {}}
        return val
    # Built-in MCP: return server.json (only costaff core MCP has a local config)
    if name == "costaff":
        path = os.path.join("mcp_servers", "costaff", "server.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    return {"name": name, "description": "No config found."}


@router.post("/api/mcp/{name}/config")
async def update_mcp_config(name: str, request: Request, auth: bool = Depends(AuthManager.verify_token)):
    body = await request.json()
    core = active_core()
    conf = core.core_config()
    if name in conf.get("external_mcp", {}):
        existing = conf["external_mcp"][name]
        if isinstance(existing, str):
            existing = {"url": existing, "transport": "sse" if "/mcp" in existing else "streamable", "enabled": True, "headers": {}}
        existing.update({k: v for k, v in body.items() if k in ("url", "transport", "enabled", "headers", "description")})
        conf["external_mcp"][name] = existing
        core.write_config(conf)
        core.regen_mcp_urls()
    elif name == "costaff":
        # Built-in MCP: update server.json (only costaff core MCP has a local config)
        path = os.path.join("mcp_servers", "costaff", "server.json")
        existing = {}
        if os.path.exists(path):
            with open(path, "r") as f:
                existing = json.load(f)
        existing.update(body)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)
    return {"status": "success"}


@router.delete("/api/mcp/{name}")
def delete_mcp(name: str, auth: bool = Depends(AuthManager.verify_token)):
    if name == "costaff":
        raise HTTPException(status_code=400, detail="Cannot delete core MCP.")
    core = active_core()
    conf = core.core_config()
    if name in conf["mcp"]:
        conf["mcp"].remove(name)
    if name in conf["external_mcp"]:
        del conf["external_mcp"][name]
    core.write_config(conf)
    core.regen_mcp_urls()
    return {"status": "success"}


@router.get("/api/agent-mcp-config")
def get_agent_mcp_config(auth: bool = Depends(AuthManager.verify_token)):
    from services.agent_components import agent_mcp_map

    return agent_mcp_map(active_core().core_config())


@router.post("/api/agent-mcp-config")
def update_agent_mcp_config(req: AgentMCPConfigRequest, auth: bool = Depends(AuthManager.verify_token)):
    from services.agent_components import set_agent_mcps

    core = active_core()
    try:
        restart = set_agent_mcps(core, req.agent_id, req.mcps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if restart:
        threading.Thread(target=restart, daemon=True).start()
    return {"status": "success", "agent_id": req.agent_id, "mcps": req.mcps}
