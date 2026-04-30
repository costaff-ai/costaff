import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from google.adk.agents import LlmAgent
from google.adk.tools import skill_toolset

from .mcp_toolsets import load_all_mcp_toolsets
from .models import selected_model
from .instruction import build_instruction
from .skills import load_all_skills
from .sub_agents import load_all_sub_agents

# Tools = MCP toolsets + Skill toolset
tools = list(load_all_mcp_toolsets())
_skills = load_all_skills()
tools.append(skill_toolset.SkillToolset(skills=_skills))
logger.info(f"Loaded {len(_skills)} skill(s): {[s.frontmatter.name for s in _skills]}")

# Sub-agents (consumed via A2A from EXTERNAL_AGENTS_CONFIG)
sub_agents = load_all_sub_agents()

# Instruction (dynamic placeholders + sub-agent SOP gating resolved here)
instruction = build_instruction(has_sub_agents=bool(sub_agents))

root_agent = LlmAgent(
    model=selected_model,
    name="costaff_agent",
    description="Orchestrates specialists for tasks.",
    instruction=instruction,
    tools=tools,
    sub_agents=sub_agents,
)
