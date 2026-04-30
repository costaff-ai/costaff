"""Skill loader: auto-discover all subfolders containing `SKILL.md` and load them.

Usage:
    from skills import load_all_skills
    skills = load_all_skills()  # returns a list of Skill objects, ready for SkillToolset

Each Skill subfolder must follow the Agent Skill specification
(https://agentskills.io/specification). To add a new Skill, drop a
`<skill-name>/SKILL.md` into this folder — it will be loaded automatically;
no manual registration in `agent.py` is needed.
"""
from pathlib import Path
from typing import List

from google.adk.skills import load_skill_from_dir

_SKILLS_DIR = Path(__file__).parent


def load_all_skills() -> List:
    """Scan the skills/ folder and load every subfolder that contains SKILL.md.

    Returns:
        List: all loaded Skill objects, ready to be passed to SkillToolset.
    """
    skills = []
    for child in sorted(_SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").exists():
            skills.append(load_skill_from_dir(child))
    return skills
