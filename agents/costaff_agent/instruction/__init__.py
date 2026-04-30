"""Auto-load `system.md` and provide instruction-building helpers.

Usage:
    from .instruction import instruction_content   # static template
    from .instruction import build_instruction     # dynamic substitution

Falls back to a generic placeholder if `system.md` is missing.
"""
import os
import re
from pathlib import Path

_SYSTEM_PATH = Path(__file__).parent / "system.md"

if _SYSTEM_PATH.exists():
    instruction_content = _SYSTEM_PATH.read_text(encoding="utf-8")
else:
    instruction_content = "You are a professional AI assistant."


def build_instruction(has_sub_agents: bool) -> str:
    """Resolve runtime placeholders in instruction_content.

    - has_sub_agents=True : strip the BEGIN/END_SUB_AGENTS marker
                            comments but keep their content (orchestration
                            SOPs and routing rules).
    - has_sub_agents=False: drop the entire BEGIN_SUB_AGENTS...END_SUB_AGENTS
                            block (so the LLM doesn't see delegation rules
                            it cannot follow) and prepend a "you work alone"
                            hint.

    Substitutes the `{PREFERRED_LANGUAGE}` placeholder with whatever
    `COSTAFF_PREFERRED_LANGUAGE` env var is set to (defaults to English).
    """
    if has_sub_agents:
        body = re.sub(r"<!--\s*(BEGIN|END)_SUB_AGENTS\s*-->", "", instruction_content)
    else:
        body = re.sub(
            r"<!--\s*BEGIN_SUB_AGENTS\s*-->.*?<!--\s*END_SUB_AGENTS\s*-->",
            "",
            instruction_content,
            flags=re.DOTALL,
        )
        body = "\n# NO SUB-AGENTS\nYou work alone.\n\n" + body

    preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "English")
    return body.replace("{PREFERRED_LANGUAGE}", preferred_lang)
