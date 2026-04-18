import os
import json
import sys
import logging
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
        url, headers, transport = entry, None, "sse" if "/mcp" in entry else "streamable"
    else:
        url       = entry.get("url", "")
        headers   = entry.get("headers") or None
        transport = entry.get("transport", "streamable")

    if not url:
        raise ValueError("MCP entry has no URL")

    if transport == "sse" or "/mcp" in url:
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
    import httpx
    import time
    metadata = {"description": f"Sub-agent: {agent_name}", "display_name": agent_name}
    
    # Paths to try
    paths = ["/.well-known/agent.json", "/.well-known/agent-card.json"]
    
    # 3 attempts with exponential backoff
    for attempt in range(3):
        for path in paths:
            try:
                url = f"{a2a_url.rstrip('/')}{path}"
                resp = httpx.get(url, timeout=5.0)
                if resp.status_code == 200:
                    card = resp.json()
                    desc = card.get("description", "").strip()
                    if desc: metadata["description"] = desc
                    # Check for display_name in capabilities
                    display_name = card.get("capabilities", {}).get("display_name", "").strip()
                    if display_name:
                        metadata["display_name"] = display_name
                        logger.info(f"Fetched display_name '{display_name}' for '{agent_name}' from {path}")
                    return metadata
            except Exception as e:
                pass
        
        if attempt < 2:
            logger.info(f"Retrying fetch for '{agent_name}' in 3s... (attempt {attempt+1})")
            time.sleep(3)
            
    logger.warning(f"Could not fetch agent card for '{agent_name}' from {a2a_url} after retries.")
    return metadata

sub_agents = []
agent_display_mappings = []
raw_agents = os.getenv("EXTERNAL_AGENTS_CONFIG", "").strip()
if raw_agents:
    try:
        from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH
        agents_config = json.loads(raw_agents)
        for agent_name, agent_cfg in agents_config.items():
            a2a_url = agent_cfg.get("a2a_url", "").strip()
            if not a2a_url:
                logger.warning(f"Skipping agent '{agent_name}': no a2a_url")
                continue
            try:
                meta = _fetch_agent_card_metadata(a2a_url, agent_name)
                remote_agent = RemoteA2aAgent(
                    name=agent_name.replace("-", "_"),
                    description=meta["description"],
                    agent_card=f"{a2a_url}{AGENT_CARD_WELL_KNOWN_PATH}",
                    use_legacy=False,
                )
                sub_agents.append(remote_agent)
                agent_display_mappings.append(f"- `{(agent_name.replace('-', '_'))}` → <b>{meta['display_name']}</b>")
                logger.info(f"Registered sub-agent '{agent_name}': {a2a_url}")
            except Exception as e:
                logger.warning(f"Failed to load agent '{agent_name}': {e}")
    except json.JSONDecodeError as e:
        logger.error(f"EXTERNAL_AGENTS_CONFIG is not valid JSON: {e}")

# Construct dynamic instruction
display_names_block = "\n".join(agent_display_mappings) if agent_display_mappings else "- (No external agents registered)"
preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")

instruction = (
    AGENT_INSTRUCTION
    .replace("{SUB_AGENT_DISPLAY_NAMES}", display_names_block)
    .replace("{PREFERRED_LANGUAGE}", preferred_lang)
)

# Define the root agent
root_agent = LlmAgent(
    model=selected_model,
    name="costaff_agent",
    description=(
        "CoStaff Agent: a personal AI assistant for scheduling, reminders, profile management, "
        "and general knowledge. "
        "Responsible for: answering questions with general knowledge; managing user profile and identity; "
        "creating and managing reminders and scheduled messages; managing Kanban tasks for recurring "
        "automated work; calling user-registered external APIs; discovering and invoking registered Skills; "
        "orchestrating sub-agents for tasks requiring code execution, data analysis, or report generation. "
        "Communicates with users via Telegram, Discord, or Line."
    ),
    instruction=instruction,
    tools=tools,
    sub_agents=sub_agents,
)
