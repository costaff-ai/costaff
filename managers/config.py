import os
import json
import time
from typing import Dict, Any
from dotenv import load_dotenv, set_key

from utils.helpers import PATHS


class ConfigManager:
    @staticmethod
    def get_config() -> Dict[str, Any]:
        if os.path.exists(PATHS["config"]):
            try:
                with open(PATHS["config"], "r") as f:
                    conf = json.load(f)
                    conf.setdefault("external_mcp", {})
                    conf.setdefault("gateways_config", {})
                    conf.setdefault("mcp", ["costaff"])
                    # Migrate legacy "platforms" key to "channels"
                    if "platforms" in conf and "channels" not in conf:
                        conf["channels"] = conf.pop("platforms")
                    conf.setdefault("channels", [])
                    conf.setdefault("require_approval", True)
                    conf.setdefault("coding_agent_enabled", False)
                    conf.setdefault("external_agents", {})
                    migrated = ConfigManager._migrate_coding_agent(conf)
                    migrated |= ConfigManager._migrate_channel_container_names(conf)
                    if migrated:
                        ConfigManager.save_config(conf)
                    return conf
            except Exception:
                pass
        return {"channels": [], "mcp": ["costaff"], "external_mcp": {}, "gateways_config": {}, "require_approval": True, "coding_agent_enabled": False, "external_agents": {}}

    @staticmethod
    def _migrate_channel_container_names(conf: Dict) -> bool:
        """Rename legacy 'costaff-chan-*' container names to 'costaff-channel-*'."""
        changed = False
        for name, entry in conf.get("dynamic_channels", {}).items():
            names = entry.get("container_names") or []
            new_names = [n.replace("costaff-chan-", "costaff-channel-") for n in names]
            if new_names != names:
                entry["container_names"] = new_names
                changed = True
        return changed

    @staticmethod
    def _migrate_coding_agent(conf: Dict) -> bool:
        """One-time migration: coding_agent_enabled → external_agents entry. Returns True if migrated."""
        if "costaff-agent-coding" in conf.get("external_agents", {}):
            return False  # already migrated
        if not conf.get("coding_agent_enabled"):
            return False  # never enabled, nothing to migrate
        load_dotenv(PATHS["env"])
        a2a_url = os.getenv("CODING_A2A_URL", "").strip() or os.getenv("CODING_A2A_INTERNAL_URL", "http://costaff-agent-coding:8081")
        conf.setdefault("external_agents", {})["costaff-agent-coding"] = {
            "type": "github",
            "a2a_url": a2a_url,
            "description": "寫程式並執行來解決需要計算、資料處理或程式邏輯的問題，回傳執行結果與產生的檔案路徑。",
            "enabled": bool(conf.get("coding_agent_enabled", False)),
            "container_names": ["costaff-agent-coding", "costaff-mcp-coding"],
        }
        return True

    @staticmethod
    def save_config(config: Dict[str, Any]):
        os.makedirs(os.path.dirname(PATHS["config"]), exist_ok=True)
        with open(PATHS["config"], "w") as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def update_mcp_urls():
        conf = ConfigManager.get_config()
        urls = {}

        load_dotenv(PATHS["env"], override=True)
        mcp_secret = os.getenv("MCP_SECRET_KEY", "").strip()

        # 1. Gather all MCP servers
        # Core MCP
        for m in conf.get("mcp", []):
            custom_url = None
            if m == "costaff":
                path = os.path.join("mcp_servers", "server.json")
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            pkg = json.load(f).get("packages", [{}])[0]
                            custom_url = pkg.get("transport", {}).get("url")
                    except Exception:
                        pass
            
            # Check if this MCP belongs to an external agent to get its custom port
            ext_agent = conf.get("external_agents", {}).get(m)
            default_port = 8081 if m == "costaff" else 8080
            if ext_agent and "mcp_port" in ext_agent:
                default_port = ext_agent["mcp_port"]
            # Known official agents fallback ports
            elif m == "coding": default_port = 8082
            elif m == "business-analysis": default_port = 8083

            url = custom_url or f"http://costaff-mcp-{m}:{default_port}/mcp"
            
            if mcp_secret:
                urls[m] = {
                    "url": url,
                    "transport": "sse" if url.rstrip("/").endswith("/sse") else "streamable",
                    "headers": {"Authorization": f"Bearer {mcp_secret}"},
                }
            else:
                urls[m] = url

        # External MCPs from config
        for name, val in conf.get("external_mcp", {}).items():
            if isinstance(val, str):
                urls[name] = val
            elif isinstance(val, dict) and val.get("enabled", True):
                if url := val.get("url"):
                    urls[name] = {k: v for k, v in val.items() if k not in ("enabled", "description")}

        os.makedirs(os.path.dirname(PATHS["env"]), exist_ok=True)
        set_key(PATHS["env"], "MCP_SERVER_URLS", json.dumps(urls))

        # 2. Map MCPs to Agents
        agent_mcps = conf.get("agent_mcps", {})

        # costaff_agent: defaults to all if not specified
        costaff_names = agent_mcps.get("costaff_agent")
        if costaff_names is None: # Use all if field is missing
            costaff_names = list(urls.keys())
        costaff_urls = {k: v for k, v in urls.items() if k in costaff_names}
        set_key(PATHS["env"], "COSTAFF_AGENT_MCP_URLS", json.dumps(costaff_urls))

        # External agents
        for ext_name, ext_agent in conf.get("external_agents", {}).items():
            if not ext_agent.get("mcp_configurable"):
                continue
            agent_key = ext_name.replace("-", "_")
            env_var = ext_agent.get("mcp_env_var") or (agent_key.upper() + "_MCP_URLS")
            
            selected = agent_mcps.get(agent_key)
            if selected is None:
                # Default: Specialist can see itself + Root Tools
                selected = ["costaff", ext_name]
            
            extra_urls = {k: v for k, v in urls.items() if k in selected}
            set_key(PATHS["env"], env_var, json.dumps(extra_urls))
            print(f"[MCP] Wrote {env_var}: {list(extra_urls.keys())}")

        # Important: Allow a small window for disk sync and reload env
        time.sleep(0.5)
        load_dotenv(PATHS["env"], override=True)

    @staticmethod
    def update_external_agents_env():
        """Serialize enabled external_agents into EXTERNAL_AGENTS_CONFIG env var."""
        conf = ConfigManager.get_config()
        agents_config = {}
        for name, agent in conf.get("external_agents", {}).items():
            if agent.get("enabled", True) and agent.get("a2a_url"):
                agents_config[name] = {
                    "a2a_url": agent["a2a_url"],
                    "description": agent.get("description", ""),
                }
        set_key(PATHS["env"], "EXTERNAL_AGENTS_CONFIG", json.dumps(agents_config))
        load_dotenv(PATHS["env"], override=True)
