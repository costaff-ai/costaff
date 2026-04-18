import os
import json
import subprocess
import threading

from fastapi import APIRouter, HTTPException, Depends, Request
from dotenv import load_dotenv, set_key

from managers.auth import AuthManager
from managers.config import ConfigManager
from managers.docker import DockerManager
from models.requests import GatewayUpdateRequest, AddMCPRequest, AgentMCPConfigRequest
from utils.helpers import PATHS, _project_root, _runtime_root, _runtime_root

router = APIRouter()


@router.get("/api/config")
def get_api_config(auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    load_dotenv(PATHS["env"])
    # Sync environment tokens to the config object for UI
    if "gateways_config" not in conf:
        conf["gateways_config"] = {}
    tokens = {"tg": "TELEGRAM_BOT_TOKEN", "dc": "DISCORD_BOT_TOKEN", "line": "LINE_CHANNEL_ACCESS_TOKEN"}
    for k, v in tokens.items():
        if t := os.getenv(v):
            conf["gateways_config"].setdefault(k, {})["token"] = t
    return conf


@router.post("/api/config/coding-agent")
def set_coding_agent(req: dict, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    enabled_changed = "enabled" in req
    if enabled_changed:
        enabled = bool(req["enabled"])
        conf["coding_agent_enabled"] = enabled
        # Keep external_agents in sync
        coding_a2a_url = os.getenv("CODING_A2A_INTERNAL_URL", "http://coding-agent:8081")
        conf.setdefault("external_agents", {}).setdefault("coding-agent", {
            "type": "github",
            "a2a_url": coding_a2a_url,
            "description": "寫程式並執行來解決需要計算、資料處理或程式邏輯的問題，回傳執行結果與產生的檔案路徑。",
            "container_names": ["coding-agent", "mcp-coding"],
        })["enabled"] = enabled
        conf["external_agents"]["coding-agent"]["a2a_url"] = coding_a2a_url
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()

    if enabled_changed:
        enabled = conf["coding_agent_enabled"]
        def _apply_docker():
            load_dotenv(PATHS["env"], override=True)
            compose_file = "docker-compose.yaml"
            compose_cwd = DockerManager.get_compose_cwd(compose_file)
            cmd_base = DockerManager.get_cmd() + ["-f", compose_file]
            if enabled:
                subprocess.run(
                    cmd_base + ["--profile", "coding", "up", "-d", "mcp-coding", "coding-agent"],
                    check=False, cwd=compose_cwd
                )
            else:
                subprocess.run(
                    cmd_base + ["stop", "coding-agent", "mcp-coding"],
                    check=False, cwd=compose_cwd
                )
            DockerManager.run_action("costaff-agent", "restart")
        threading.Thread(target=_apply_docker, daemon=True).start()

    return {"status": "ok", "coding_agent_enabled": conf["coding_agent_enabled"]}


@router.post("/api/gateways")
def save_gateway(req: GatewayUpdateRequest, auth: bool = Depends(AuthManager.verify_token)):
    token_env_map = {"tg": "TELEGRAM_BOT_TOKEN", "dc": "DISCORD_BOT_TOKEN", "line": "LINE_CHANNEL_ACCESS_TOKEN"}
    secret_env_map = {"line": "LINE_CHANNEL_SECRET"}
    p = req.platform
    if p not in token_env_map:
        raise HTTPException(status_code=400, detail="Unknown platform.")
    # Save token to .env
    if token := req.config.get("token"):
        set_key(PATHS["env"], token_env_map[p], token)
    if secret := req.config.get("secret"):
        if p in secret_env_map:
            set_key(PATHS["env"], secret_env_map[p], secret)
    # Add to channels if not already present
    conf = ConfigManager.get_config()
    if p not in conf.get("channels", []):
        conf.setdefault("channels", []).append(p)
    ConfigManager.save_config(conf)
    return {"status": "ok"}


@router.post("/api/mcp")
def add_mcp(req: AddMCPRequest, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
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

    ConfigManager.save_config(conf)
    if req.config and req.name == "costaff":
        path = os.path.join("mcp_servers", "costaff", "server.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(req.config, f, indent=2)

    ConfigManager.update_mcp_urls()
    return {"status": "success"}


@router.get("/api/mcp/{name}/config")
def get_mcp_config(name: str, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
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
    conf = ConfigManager.get_config()
    if name in conf.get("external_mcp", {}):
        existing = conf["external_mcp"][name]
        if isinstance(existing, str):
            existing = {"url": existing, "transport": "sse" if "/mcp" in existing else "streamable", "enabled": True, "headers": {}}
        existing.update({k: v for k, v in body.items() if k in ("url", "transport", "enabled", "headers", "description")})
        conf["external_mcp"][name] = existing
        ConfigManager.save_config(conf)
        ConfigManager.update_mcp_urls()
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
    conf = ConfigManager.get_config()
    if name in conf["mcp"]:
        conf["mcp"].remove(name)
    if name in conf["external_mcp"]:
        del conf["external_mcp"][name]
    ConfigManager.save_config(conf)
    ConfigManager.update_mcp_urls()
    return {"status": "success"}


@router.get("/api/agent-mcp-config")
def get_agent_mcp_config(auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    all_mcp_names = list(conf.get("mcp", []))
    for name, val in conf.get("external_mcp", {}).items():
        enabled = val.get("enabled", True) if isinstance(val, dict) else True
        if enabled:
            all_mcp_names.append(name)

    agent_mcps = conf.get("agent_mcps", {})

    result_mcps = {
        "costaff_agent": agent_mcps.get("costaff_agent", all_mcp_names),
    }
    # Include github-type external agents (URL agents are not managed by CoStaff)
    for name, agent in conf.get("external_agents", {}).items():
        if agent.get("type") == "github":
            agent_key = name.replace("-", "_")
            result_mcps[agent_key] = agent_mcps.get(agent_key, all_mcp_names)

    return {"available_mcps": all_mcp_names, "agent_mcps": result_mcps}


@router.post("/api/agent-mcp-config")
def update_agent_mcp_config(req: AgentMCPConfigRequest, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    agent_mcps = conf.get("agent_mcps", {})
    agent_mcps[req.agent_id] = req.mcps
    conf["agent_mcps"] = agent_mcps
    ConfigManager.save_config(conf)
    ConfigManager.update_mcp_urls()

    # Find if this is a github-type external agent (has its own compose fragment)
    agent_id_to_name = {n.replace("-", "_"): n for n in conf.get("external_agents", {})}
    ext_name = agent_id_to_name.get(req.agent_id)
    ext_agent_conf = conf.get("external_agents", {}).get(ext_name) if ext_name else None

    if ext_agent_conf and ext_agent_conf.get("type") == "github" and ext_agent_conf.get("fragment_path"):
        # Restart using the compose fragment so service definition is available
        main_compose = os.path.join(_runtime_root, "docker-compose.yaml")
        fragment_path = ext_agent_conf["fragment_path"]
        primary_service = ext_agent_conf.get("container_names", [ext_name])[0]
        def _restart_ext_agent():
            load_dotenv(PATHS["env"], override=True)
            stop_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "stop", primary_service]
            subprocess.run(stop_cmd, check=False, cwd=_project_root)
            up_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d", "--force-recreate", primary_service]
            subprocess.run(up_cmd, check=False, cwd=_project_root)
            print(f"[MCP] Restarted external agent {ext_name} ({primary_service})")
        threading.Thread(target=_restart_ext_agent, daemon=True).start()
    else:
        # Internal agent (costaff-agent, coding-agent legacy, etc.)
        docker_name_map = {"costaff_agent": "costaff-agent", "coding_agent": "coding-agent"}
        docker_service = docker_name_map.get(req.agent_id)
        if docker_service:
            threading.Thread(target=DockerManager.run_action, args=(docker_service, "restart"), daemon=True).start()

    return {"status": "success", "agent_id": req.agent_id, "mcps": req.mcps}
