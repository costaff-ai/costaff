import os
import json
import sys
import logging
import httpx
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to sys.path to ensure utils can be imported correctly in the container
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseServerParams, StreamableHTTPServerParams
from utils.models.litellm_model.litellm_model_config import litellm_model
from utils.instructions import AGENT_INSTRUCTION

# --- Configuration ---
# Prefer per-agent MCP URLs; fall back to shared MCP_SERVER_URLS
raw_config = os.getenv("COSTAFF_AGENT_MCP_URLS") or os.getenv("MCP_SERVER_URLS", "")
logger.info(f"Loading MCP config: {raw_config}")

if not raw_config:
    raise EnvironmentError("COSTAFF_AGENT_MCP_URLS (or MCP_SERVER_URLS) is not set.")

try:
    mcp_config = json.loads(raw_config)
except json.JSONDecodeError:
    # Legacy comma-separated URL list
    mcp_config = {f"mcp_{i}": url.strip() for i, url in enumerate(raw_config.split(",")) if url.strip()}

def get_connection_params(entry):
    """
    Accepts either:
      - a plain URL string (legacy)
      - a Dive-format dict: { url, transport, headers, enabled }
    """
    if isinstance(entry, str):
        url, headers, transport = entry, None, None
    else:
        url       = entry.get("url", "")
        headers   = entry.get("headers") or None
        transport = entry.get("transport")

    if not url:
        raise ValueError("MCP entry has no URL")

    # Infer transport from URL path when not explicitly set: /sse → SSE, /mcp → streamable-http.
    if transport is None:
        transport = "sse" if url.rstrip("/").endswith("/sse") else "streamable"

    if transport == "sse":
        logger.info(f"Using SSE for {url}")
        return SseServerParams(url=url, headers=headers)

    logger.info(f"Using Streamable HTTP for {url}")
    return StreamableHTTPServerParams(url=url, headers=headers)

# Define tools with resilience
tools = []
for name, entry in mcp_config.items():
    if isinstance(entry, dict) and not entry.get("enabled", True):
        logger.info(f"Skipping disabled MCP: {name}")
        continue
    try:
        tools.append(McpToolset(connection_params=get_connection_params(entry)))
        logger.info(f"Successfully registered MCP toolset: {name}")
    except Exception as e:
        logger.error(f"FAILED to load MCP '{name}': {e}")

# Define the model to use
model_provider = (os.getenv("COSTAFF_AGENT_MODEL_PROVIDER") or "gemini").lower()
model_name = os.getenv("COSTAFF_AGENT_GEMINI_MODEL", "gemini-2.5-flash")

if model_provider == "litellm":
    selected_model = litellm_model
    logger.info(f"Using LiteLLM model provider")
else:
    selected_model = model_name
    logger.info(f"Using Gemini model provider: {selected_model}")

# --- Sub-Agents (RemoteA2aAgent via A2A) ---
# Loaded dynamically from EXTERNAL_AGENTS_CONFIG env var (JSON dict: name -> {a2a_url})
# Metadata is fetched from each agent's own agent card at startup.
def _fetch_agent_card_metadata(a2a_url: str, agent_name: str) -> dict:
    """Fetch metadata from agent card. Tries multiple well-known paths and includes retries."""
    metadata = {
        "description": f"Sub-agent: {agent_name}", 
        "display_name": agent_name,
        "skills": []
    }
    
    # Paths to try
    paths = ["/.well-known/agent.json", "/.well-known/agent-card.json"]
    
    # 5 attempts with exponential backoff (max ~40 seconds)
    for attempt in range(5):
        for path in paths:
            try:
                url = f"{a2a_url.rstrip('/')}{path}"
                resp = httpx.get(url, timeout=10.0)
                if resp.status_code == 200:
                    card = resp.json()
                    desc = card.get("description", "").strip()
                    if desc: metadata["description"] = desc
                    
                    # Extract Skills
                    skills = card.get("skills", [])
                    if skills:
                        metadata["skills"] = [s.get("name") if isinstance(s, dict) else str(s) for s in skills]

                    # Check for display_name in capabilities
                    display_name = card.get("capabilities", {}).get("display_name", "").strip()
                    if display_name:
                        metadata["display_name"] = display_name
                        logger.info(f"Fetched display_name '{display_name}' for '{agent_name}' from {path}")
                    return metadata
            except Exception as e:
                pass
        
        if attempt < 4:
            wait_time = (attempt + 1) * 3
            logger.info(f"Retrying fetch for '{agent_name}' in {wait_time}s... (attempt {attempt+1}/5)")
            time.sleep(wait_time)
            
    logger.warning(f"Could not fetch agent card for '{agent_name}' from {a2a_url} after retries.")
    return metadata

sub_agents = []
agent_meta_cache = {} 
raw_agents = os.getenv("EXTERNAL_AGENTS_CONFIG", "").strip()
if raw_agents:
    try:
        from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH
        agents_config = json.loads(raw_agents)
        for agent_name, agent_cfg in agents_config.items():
            a2a_url = agent_cfg.get("a2a_url", "").strip()
            if not a2a_url:
                continue
            try:
                logger.info(f"Registering sub-agent '{agent_name}' with URL: {a2a_url}")
                meta = _fetch_agent_card_metadata(a2a_url, agent_name)
                a2a_name = agent_name.replace("-", "_")
                agent_meta_cache[a2a_name] = meta
                
                remote_agent = RemoteA2aAgent(
                    name=a2a_name,
                    description=meta["description"],
                    agent_card=f"{a2a_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}",
                    use_legacy=False,
                )
                sub_agents.append(remote_agent)
                logger.info(f"Successfully registered sub-agent '{a2a_name}' (from {agent_name})")
            except Exception as e:
                logger.error(f"CRITICAL: Failed to load sub-agent '{agent_name}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"EXTERNAL_AGENTS_CONFIG load error: {e}")

# Construct dynamic instruction
import re
preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")

if sub_agents:
    roster_lines = [
        "## 🛠 團隊專家名冊 (Current Team Roster)",
        "當你收到任務時，請優先核對此名冊。你具備以下所有專家的擴展能力：",
        ""
    ]
    for a2a_name, meta in agent_meta_cache.items():
        roster_lines.append(f"### 🤖 專家 ID: `{a2a_name}`")
        roster_lines.append(f"- **職責描述**: {meta['description']}")
        
        if meta.get("skills"):
            skill_list = ", ".join([f"`{s}`" for s in meta["skills"]])
            roster_lines.append(f"- **具備技能**: {skill_list}")
        
        if "coding" in a2a_name:
            roster_lines.append("- **核心能力**: [CRITICAL] 這是你唯一具備編寫程式、處理檔案、修復 CSV 與執行數學運算的能力來源。")
        if "ba_agent" in a2a_name or "business" in a2a_name:
            roster_lines.append("- **核心能力**: [CRITICAL] 這是你唯一具備生成視覺化圖表與 BI 報告的能力來源。")
            
        roster_lines.append(f"- **調用指令**: 只要任務涉及上述能力，你「必須」立即呼叫 `transfer_to_agent(agent_name='{a2a_name}')`。")
        roster_lines.append("")
    
    display_names_block = "\n".join(roster_lines)
    # Keep content, strip only the marker comments.
    instruction_body = re.sub(r"<!--\s*(BEGIN|END)_SUB_AGENTS\s*-->", "", AGENT_INSTRUCTION)
else:
    display_names_block = ""
    # Remove entire sub-agent blocks including markers (DOTALL so . matches newlines).
    instruction_body = re.sub(
        r"<!--\s*BEGIN_SUB_AGENTS\s*-->.*?<!--\s*END_SUB_AGENTS\s*-->",
        "",
        AGENT_INSTRUCTION,
        flags=re.DOTALL,
    )
    # Explicit negative assertion
    no_subs_guard = (
        "\n# NO SUB-AGENTS (CRITICAL)\n"
        "You currently have **NO registered sub-agents**. You work alone.\n"
        "- If the user asks about team members, specialists, coding assistants, or any named agent "
        "answer truthfully: **no such sub-agent is registered**.\n\n---\n"
    )
    instruction_body = no_subs_guard + instruction_body

instruction = (
    instruction_body
    .replace("{SUB_AGENT_DISPLAY_NAMES}", display_names_block)
    .replace("{PREFERRED_LANGUAGE}", preferred_lang)
)

# Define the root agent
description_parts = [
    "CoStaff Agent: a personal AI assistant.",
    "Responsible for: scheduling, reminders, profile management, and general knowledge.",
]
if sub_agents:
    description_parts.append("Orchestrates registered sub-agents for specialised tasks.")

root_agent = LlmAgent(
    model=selected_model,
    name="costaff_agent",
    description=" ".join(description_parts),
    instruction=instruction,
    tools=tools,
    sub_agents=sub_agents,
)
