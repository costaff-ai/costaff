import os
import json
import time
import warnings
from typing import Dict, Any
from dotenv import load_dotenv, set_key

from utils.paths import PATHS

# The four manager-core MCP tools every plugin agent needs (Agent Protocol
# v1.x): progress notify / task comment / file hand-off / file listing.
# `costaff agent add` seeds agent_mcp_filters with exactly this set so a
# fresh sub-agent doesn't inherit the manager's full ~40-tool spec.
CORE_PLUGIN_MCP_TOOLS = (
    "send_message_now", "add_task_comment", "move_to_shared", "list_data_files",
)


class ConfigCorruptError(RuntimeError):
    """config.json exists but cannot be read/parsed — refuse to continue."""


class ConfigManager:
    @staticmethod
    def get_config(config_path: str = None) -> Dict[str, Any]:
        cp = config_path or PATHS["config"]
        if os.path.exists(cp):
            # A corrupt config must be LOUD. Silently returning the empty
            # default here meant the very next save_config() overwrote the
            # file with it, wiping every registered agent/channel/core.
            try:
                with open(cp, "r") as f:
                    conf = json.load(f)
            except (ValueError, OSError) as e:
                raise ConfigCorruptError(
                    f"{cp} is unreadable ({e}). Fix or restore the file "
                    "(check for a stray comma/quote), or delete it to start "
                    "from an empty config — refusing to continue, because "
                    "the next save would overwrite it and drop every "
                    "registered agent/channel."
                ) from e
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
                ConfigManager.save_config(conf, cp)
            ConfigManager._warn_if_invalid(conf)
            return conf
        return {"channels": [], "mcp": ["costaff"], "external_mcp": {}, "gateways_config": {}, "require_approval": True, "coding_agent_enabled": False, "external_agents": {}}

    @staticmethod
    def _warn_if_invalid(conf: Dict[str, Any]) -> None:
        """Soft validation against CoStaffConfig — warn only, never crash.

        Keeping this non-fatal preserves graceful degradation; `costaff config
        validate` is the strict entry point that exits non-zero on errors.
        """
        try:
            from services.config_schema import CoStaffConfig
            CoStaffConfig.model_validate(conf)
        except Exception as e:
            warnings.warn(f"config.json failed schema validation: {e}", stacklevel=3)

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
            "description": "Writes and runs code to solve problems involving computation, data processing, or program logic. Returns execution results and generated file paths.",
            "enabled": bool(conf.get("coding_agent_enabled", False)),
            "container_names": ["costaff-agent-coding", "costaff-mcp-coding"],
        }
        return True

    @staticmethod
    def save_config(config: Dict[str, Any], config_path: str = None):
        cp = config_path or PATHS["config"]
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        with open(cp, "w") as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def update_mcp_urls(config_path: str = None, env_path: str = None, prefix: str = "costaff"):
        cp = config_path or PATHS["config"]
        ep = env_path or PATHS["env"]
        conf = ConfigManager.get_config(cp)
        urls = {}

        load_dotenv(ep, override=True)
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

            url = custom_url or f"http://{prefix}-mcp-{m}:{default_port}/mcp"

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

        os.makedirs(os.path.dirname(ep), exist_ok=True)
        set_key(ep, "MCP_SERVER_URLS", json.dumps(urls), quote_mode="never")

        # 2. Map MCPs to Agents
        agent_mcps = conf.get("agent_mcps", {})

        # costaff_agent (the manager) defaults to its own core MCP only.
        #
        # Why not all MCPs: ADK initialises every McpToolset in parallel at
        # agent boot. With N streamable-http MCPs the anyio task group hits
        # `Attempted to exit cancel scope in a different task` races, the LLM
        # then sees an incomplete tool list and fabricates "delegated to X"
        # replies referencing files that never get written. The manager talks
        # to sub-agents via A2A AgentTool — it does NOT need their MCPs to
        # delegate; sub-agents load their own MCPs themselves. Override in
        # config.json's `agent_mcps.costaff_agent` to broaden if you need it.
        costaff_names = agent_mcps.get("costaff_agent")
        if costaff_names is None:
            costaff_names = ["costaff"]
        elif costaff_names != ["costaff"]:
            print(
                f"[MCP] WARNING: agent_mcps.costaff_agent={costaff_names} "
                f"overrides the invariant `manager → own MCP only`. "
                f"The manager reaches sub-agents via A2A AgentTool, NOT via MCP, "
                f"so listing extra MCPs here only invites the ADK anyio task "
                f"group race ('cancel scope in different task'). "
                f"Set `\"costaff_agent\": [\"costaff\"]` (or remove the key) to "
                f"restore the invariant."
            )
        costaff_urls = {k: v for k, v in urls.items() if k in costaff_names}
        # quote_mode="never" matters: python-dotenv's default wraps JSON values
        # in single quotes, but docker compose's env_file parser strips
        # single-quoted values to empty (its `${VAR}` interpolation does parse
        # them, hence manager works while sub-agents loaded via env_file get
        # empty). Write JSON raw so both parsers agree.
        set_key(ep, "COSTAFF_AGENT_MCP_URLS", json.dumps(costaff_urls), quote_mode="never")

        # Per-agent MCP tool whitelists. Schema in config.json:
        #   "agent_mcp_filters": {
        #     "<agent_key>": {
        #       "<mcp_name>": ["tool_a", "tool_b"]   # only these tools enter the agent's spec
        #     }
        #   }
        # Why: when a sub-agent connects to the manager core MCP it inherits
        # ~40 tools, most irrelevant to its job (epic/story/diary etc.).
        # Bloat costs tokens on every LLM call and increases mis-selection.
        # A whitelist keeps each plugin's tool spec small and focused.
        agent_mcp_filters = conf.get("agent_mcp_filters", {})

        # External agents
        for ext_name, ext_agent in conf.get("external_agents", {}).items():
            if not ext_agent.get("mcp_configurable"):
                continue
            agent_key = ext_name.replace("-", "_")
            env_var = ext_agent.get("mcp_env_var") or (agent_key.upper() + "_MCP_URLS")

            selected = agent_mcps.get(agent_key)
            expected = ["costaff", ext_name]
            if selected is None:
                # Default: Specialist can see itself + Root Tools (costaff)
                selected = expected
            elif set(selected) != set(expected):
                # Sub-agents need BOTH their own MCP (real work tools) AND the
                # manager core MCP (the 4 cross-agent tools:
                # send_message_now / add_task_comment / move_to_shared /
                # list_data_files). Dropping the manager core MCP breaks the
                # agent's instruction contract (it fail-fasts when
                # `send_message_now` is missing); adding more MCPs raises the
                # anyio race odds without benefit.
                print(
                    f"[MCP] WARNING: agent_mcps.{agent_key}={selected} "
                    f"overrides the invariant `sub-agent → [costaff, own]`. "
                    f"Expected: {expected}. "
                    f"Set or remove the key in config.json to restore."
                )

            extra_urls = {}
            filters_for_agent = agent_mcp_filters.get(agent_key, {})
            for k, v in urls.items():
                if k not in selected:
                    continue
                tool_filter = filters_for_agent.get(k)
                if tool_filter and isinstance(v, dict):
                    extra_urls[k] = {**v, "tool_filter": tool_filter}
                elif tool_filter and isinstance(v, str):
                    # Promote string URL to dict so we can attach the filter
                    extra_urls[k] = {"url": v, "tool_filter": tool_filter}
                else:
                    extra_urls[k] = v

            set_key(ep, env_var, json.dumps(extra_urls), quote_mode="never")
            filter_summary = {k: len(filters_for_agent[k]) for k in filters_for_agent if k in extra_urls}
            if filter_summary:
                print(f"[MCP] Wrote {env_var}: {list(extra_urls.keys())} (filters: {filter_summary})")
            else:
                print(f"[MCP] Wrote {env_var}: {list(extra_urls.keys())}")

        # Important: Allow a small window for disk sync and reload env
        time.sleep(0.5)
        load_dotenv(ep, override=True)

    @staticmethod
    def update_external_agents_env(config_path: str = None, env_path: str = None):
        """Serialize enabled external_agents into EXTERNAL_AGENTS_CONFIG env var."""
        ep = env_path or PATHS["env"]
        conf = ConfigManager.get_config(config_path)
        agents_config = {}
        transfer_names = []
        for name, agent in conf.get("external_agents", {}).items():
            if agent.get("enabled", True) and agent.get("a2a_url"):
                agents_config[name] = {
                    "a2a_url": agent["a2a_url"],
                    "description": agent.get("description", ""),
                }
                # config.json's per-agent `transfer` flag is the source of
                # truth; the Manager reads COSTAFF_TRANSFER_AGENTS (see
                # agents/costaff_agent/sub_agents/_transfer_agent_names) to
                # decide AgentTool (default) vs sub_agents/transfer wiring.
                if agent.get("transfer"):
                    transfer_names.append(name)
        set_key(ep, "EXTERNAL_AGENTS_CONFIG", json.dumps(agents_config))
        set_key(
            ep, "COSTAFF_TRANSFER_AGENTS",
            ",".join(sorted(transfer_names)), quote_mode="never",
        )
        load_dotenv(ep, override=True)
