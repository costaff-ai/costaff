"""`costaff agent ...` command group — registry only.

This module owns the shared `agent_app = typer.Typer(...)` instance. The
concrete commands live in domain-focused submodules:

  agent_lifecycle  — add / remove / enable / disable
  agent_container  — list / restart / rebuild
  agent_model      — model (and the env-file read/write helpers)

Each submodule does `from .agent import agent_app` and decorates its
functions with `@agent_app.command(...)`. We import the submodules below
purely for those decorator side effects so all subcommands appear under
`costaff agent ...` once this module is loaded.
"""
import typer

agent_app = typer.Typer(help="Manage external agents.")


# Subcommand modules — imported for their @agent_app.command(...) side effects.
from . import agent_lifecycle  # noqa: E402,F401  add / remove / enable / disable
from . import agent_container  # noqa: E402,F401  list / restart / rebuild
from . import agent_model      # noqa: E402,F401  model
from . import agent_components  # noqa: E402,F401  mcp list/set + skills (component layer)
