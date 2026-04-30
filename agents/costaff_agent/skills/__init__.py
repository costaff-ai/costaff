"""Skill loader: auto-discover all subfolders containing `SKILL.md` and wrap them as a SkillToolset.

Usage:
    from .skills import load_all_skills
    toolset = load_all_skills()  # returns a SkillToolset ready for Agent(tools=[...])

Each Skill subfolder must follow the Agent Skill specification
(https://agentskills.io/specification). To add a new Skill, drop a
`<skill-name>/SKILL.md` into this folder — it will be loaded automatically;
no manual registration in `agent.py` is needed.

Returning a `SkillToolset` (rather than a raw list of Skill objects) keeps
the wrapping concern next to the data it operates on, so `agent.py` only
needs to drop the toolset into `tools=[...]`.
"""
import logging
from pathlib import Path

from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent


def load_all_skills():
    """Scan the skills/ folder and return a SkillToolset containing every
    subfolder that has a SKILL.md.

    Returns:
        SkillToolset: ready to drop into `Agent(tools=[..., toolset])`.
    """
    skills = []
    for child in sorted(_SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").exists():
            skills.append(load_skill_from_dir(child))
    if skills:
        logger.info(f"Loaded {len(skills)} skill(s): {[s.frontmatter.name for s in skills]}")
    return skill_toolset.SkillToolset(skills=skills)
