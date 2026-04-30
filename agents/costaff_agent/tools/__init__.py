"""Plain Python function tools — always available to the LLM
(unlike SkillToolset, which loads skills on demand).

To add a new tool:
    1. Create <tool_name>.py in this folder, defining a function with a
       clear docstring (the docstring tells the agent when to call this tool).
    2. Import the function here and add it to __all__.
    3. In agent.py, import from tools and include it either directly:
           from tools import get_current_time
           Agent(tools=[..., get_current_time])
       or bundled with skills via SkillToolset(additional_tools=[...]).

Mirrors the convention from idea/google-adk-template/agent/tools/__init__.py.
The manager agent currently exposes its capabilities via MCP toolsets and
ADK Skills, so this folder is empty — kept as a placeholder for future tools.
"""

__all__: list = []
