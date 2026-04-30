import os
import json
import sys
import logging
import pathlib
import httpx
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseServerParams, StreamableHTTPServerParams
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from models.litellm_model.litellm_model_config import litellm_model
from instructions import AGENT_INSTRUCTION

# --- Configuration ---
raw_config = os.getenv("COSTAFF_AGENT_MCP_URLS") or os.getenv("MCP_SERVER_URLS", "")
if not raw_config:
    raise EnvironmentError("COSTAFF_AGENT_MCP_URLS (or MCP_SERVER_URLS) is not set.")

try:
    mcp_config = json.loads(raw_config)
except json.JSONDecodeError:
    mcp_config = {f"mcp_{i}": url.strip() for i, url in enumerate(raw_config.split(",")) if url.strip()}

def get_connection_params(entry):
    if isinstance(entry, str):
        url, headers, transport = entry, None, None
    else:
        url       = entry.get("url", "")
        headers   = entry.get("headers") or None
        transport = entry.get("transport")

    if not url: raise ValueError("MCP entry has no URL")
    if transport is None:
        transport = "sse" if url.rstrip("/").endswith("/sse") else "streamable"

    if transport == "sse":
        return SseServerParams(url=url, headers=headers)
    return StreamableHTTPServerParams(url=url, headers=headers)

tools = []
for name, entry in mcp_config.items():
    if isinstance(entry, dict) and not entry.get("enabled", True): continue
    try:
        tools.append(McpToolset(connection_params=get_connection_params(entry)))
        logger.info(f"Registered MCP: {name}")
    except Exception as e:
        logger.error(f"FAILED to load MCP '{name}': {e}")

# Load ADK Skills
_skills_dir = pathlib.Path(__file__).parent / "skills"
_skills = [
    load_skill_from_dir(d)
    for d in sorted(_skills_dir.iterdir())
    if d.is_dir() and (d / "SKILL.md").exists()
]
if _skills:
    tools.append(skill_toolset.SkillToolset(skills=_skills))
    logger.info(f"Loaded {len(_skills)} skill(s): {[d.name for d in sorted(_skills_dir.iterdir()) if d.is_dir() and (d / 'SKILL.md').exists()]}")

model_provider = (os.getenv("COSTAFF_AGENT_MODEL_PROVIDER") or "gemini").lower()
model_name = os.getenv("COSTAFF_AGENT_GEMINI_MODEL", "gemini-2.5-flash")

if model_provider == "litellm":
    selected_model = litellm_model
else:
    selected_model = model_name

# --- Sub-Agents (Consuming via A2A) ---
sub_agents = []
agent_meta_cache = {} 
raw_agents = os.getenv("EXTERNAL_AGENTS_CONFIG", "").strip()

if raw_agents:
    try:
        # Standard imports after requirements.txt is fixed
        from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH
        
        agents_config = json.loads(raw_agents)
        for agent_name, agent_cfg in agents_config.items():
            a2a_url = agent_cfg.get("a2a_url", "").strip()
            description = agent_cfg.get("description", f"Specialist: {agent_name}").strip()
            
            if not a2a_url: continue
            
            try:
                a2a_name = agent_name.replace("-", "_")
                logger.info(f"Registering sub-agent '{a2a_name}' via A2A at {a2a_url}")
                
                remote_agent = RemoteA2aAgent(
                    name=a2a_name,
                    description=description,
                    agent_card=f"{a2a_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}",
                    use_legacy=False,
                )
                sub_agents.append(remote_agent)
                agent_meta_cache[a2a_name] = {"description": description}
                logger.info(f"Successfully registered sub-agent '{a2a_name}'")
            except Exception as e:
                logger.error(f"Failed to load sub-agent '{agent_name}': {e}")
    except Exception as e:
        logger.error(f"A2A system failure: {e}")

# Construct dynamic instruction
import re
preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")

if sub_agents:
    roster_lines = ["## 🛠 團隊專家名冊 (Current Team Roster)", "當你收到任務時，請優先核對此名冊：", ""]
    for a2a_name, meta in agent_meta_cache.items():
        roster_lines.append(f"### 🤖 專家 ID: `{a2a_name}`")
        roster_lines.append(f"- **職責描述**: {meta['description']}")
        roster_lines.append(f"- **調用指令**: `transfer_to_agent(agent_name='{a2a_name}')`")
        roster_lines.append("")
    
    display_names_block = "\n".join(roster_lines)
    instruction_body = re.sub(r"<!--\s*(BEGIN|END)_SUB_AGENTS\s*-->", "", AGENT_INSTRUCTION)
else:
    display_names_block = ""
    instruction_body = re.sub(r"<!--\s*BEGIN_SUB_AGENTS\s*-->.*?<!--\s*END_SUB_AGENTS\s*-->", "", AGENT_INSTRUCTION, flags=re.DOTALL)
    instruction_body = "\n# NO SUB-AGENTS\nYou work alone.\n\n" + instruction_body

instruction = instruction_body.replace("{SUB_AGENT_DISPLAY_NAMES}", display_names_block).replace("{PREFERRED_LANGUAGE}", preferred_lang)

root_agent = LlmAgent(
    model=selected_model,
    name="costaff_agent",
    description="Orchestrates specialists for tasks.",
    instruction=instruction,
    tools=tools,
    sub_agents=sub_agents,
)
