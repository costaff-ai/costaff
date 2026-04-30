import os
import json
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from google.adk.agents import LlmAgent
from google.adk.tools import skill_toolset

from .mcp_toolsets import load_all_mcp_toolsets
from .models.litellm_model import litellm_model
from .instruction import instruction_content
from .skills import load_all_skills

# Load MCP toolsets
tools = list(load_all_mcp_toolsets())

# Load ADK Skills
_skills = load_all_skills()
tools.append(skill_toolset.SkillToolset(skills=_skills))
logger.info(f"Loaded {len(_skills)} skill(s): {[s.frontmatter.name for s in _skills]}")

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
preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "English")

if sub_agents:
    roster_lines = ["## 🛠 Current Team Roster", "When you receive a task, consult this roster first:", ""]
    for a2a_name, meta in agent_meta_cache.items():
        roster_lines.append(f"### 🤖 Specialist ID: `{a2a_name}`")
        roster_lines.append(f"- **Role**: {meta['description']}")
        roster_lines.append(f"- **Invocation**: `transfer_to_agent(agent_name='{a2a_name}')`")
        roster_lines.append("")
    
    display_names_block = "\n".join(roster_lines)
    instruction_body = re.sub(r"<!--\s*(BEGIN|END)_SUB_AGENTS\s*-->", "", instruction_content)
else:
    display_names_block = ""
    instruction_body = re.sub(r"<!--\s*BEGIN_SUB_AGENTS\s*-->.*?<!--\s*END_SUB_AGENTS\s*-->", "", instruction_content, flags=re.DOTALL)
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
