"""Auto-load `system.md` from this folder as the agent's system prompt.

Usage:
    from instruction import instruction_content

Falls back to a generic placeholder if `system.md` is missing.
"""
from pathlib import Path

_SYSTEM_PATH = Path(__file__).parent / "system.md"

if _SYSTEM_PATH.exists():
    instruction_content = _SYSTEM_PATH.read_text(encoding="utf-8")
else:
    instruction_content = "You are a professional AI assistant."
