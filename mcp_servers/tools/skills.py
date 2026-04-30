import json

from core import models
from core.database import SessionLocal
from mcp_servers.setup import mcp


def _get_accessible_skill_configs(db, user_id: str, agent_id: str = "__all__"):
    all_skills = db.query(models.SkillConfig).filter(models.SkillConfig.is_active == True).all()
    result = []
    for s in all_skills:
        if not any(uid.strip() in (user_id, "__global__") for uid in s.user_id.split(',')):
            continue
        a_ids = s.agent_ids or "__all__"
        if agent_id == "__all__" or a_ids == "__all__" or any(aid.strip() in (agent_id, "__all__") for aid in a_ids.split(',')):
            result.append(s)
    return result


@mcp.tool()
async def get_skills(user_id: str, agent_id: str = "__all__") -> str:
    """Returns a brief index of all active Skills available to this user and agent."""
    db = SessionLocal()
    try:
        skills = _get_accessible_skill_configs(db, user_id, agent_id)
        if not skills:
            return "No skills registered."
        return json.dumps([{"name": s.name, "description": s.description or ""} for s in skills], ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
async def search_skill(user_id: str, query: str, agent_id: str = "__all__") -> str:
    """Searches available Skills by matching the query against name, description, and tags."""
    db = SessionLocal()
    try:
        skills = _get_accessible_skill_configs(db, user_id, agent_id)
        q = query.lower()
        matched = [s for s in skills if q in (s.name or "").lower() or q in (s.description or "").lower() or q in (s.tags or "").lower()]
        if not matched:
            return f"No skills found matching '{query}'."
        return json.dumps([{"name": s.name, "description": s.description or "", "tags": s.tags or ""} for s in matched], ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
async def get_skill_detail(user_id: str, skill_name: str, agent_id: str = "__all__") -> str:
    """Returns the full detail of a specific Skill including usage instructions."""
    db = SessionLocal()
    try:
        all_candidates = db.query(models.SkillConfig).filter(
            models.SkillConfig.name == skill_name, models.SkillConfig.is_active == True
        ).all()
        skill = next((
            s for s in all_candidates
            if any(uid.strip() in (user_id, "__global__") for uid in s.user_id.split(','))
            and (not s.agent_ids or s.agent_ids == "__all__" or agent_id == "__all__"
                 or any(aid.strip() in (agent_id, "__all__") for aid in s.agent_ids.split(',')))
        ), None)
        if not skill:
            return f"Skill '{skill_name}' not found."
        return json.dumps({
            "name": skill.name, "description": skill.description or "",
            "tags": skill.tags or "", "usage": skill.usage or "(No usage instructions provided)"
        }, ensure_ascii=False, indent=2)
    finally:
        db.close()
