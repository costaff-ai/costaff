"""`costaff agent mcp ...` / `costaff agent skills` — Component layer.

Mirrors the dashboard's per-agent MCP / Skill cards, on the ACTIVE core
(`costaff core use <name>` to switch — the same pointer the dashboard
switcher writes). Semantics are shared with the dashboard via
services/agent_components.py, so setting MCPs here does exactly what the
UI card does: write ``agent_mcps``, regen the MCP URL env vars, recreate
the affected container.

Decorators register against `agent_app` from cli/commands/agent.py.
"""
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from services.agent_components import agent_mcp_map, fetch_agent_card, set_agent_mcps
from services.cores import active_core

from .agent import agent_app

console = Console()

mcp_app = typer.Typer(help="Per-agent MCP assignment (same semantics as the dashboard's MCP cards).")
agent_app.add_typer(mcp_app, name="mcp")


@mcp_app.command("list")
def mcp_list(agent: Optional[str] = typer.Argument(None, help="Agent id (e.g. costaff_agent, coding). Omit for all.")):
    """Show which MCP servers each agent is wired to on the active core."""
    core = active_core()
    data = agent_mcp_map(core.core_config())
    assigned = data["agent_mcps"]

    if agent:
        key = agent.replace("-", "_")
        if key not in assigned:
            console.print(f"[red]Unknown agent '{agent}'. Known: {', '.join(assigned)}[/red]")
            raise typer.Exit(1)
        assigned = {key: assigned[key]}

    table = Table(title=f"Agent → MCP wiring (core: {core.name})")
    table.add_column("Agent", style="cyan")
    table.add_column("MCP Servers")
    explicit = core.core_config().get("agent_mcps", {})
    for key, mcps in assigned.items():
        label = ", ".join(mcps) if mcps else "—"
        if key not in explicit:
            label += "  [dim](default: all)[/dim]"
        table.add_row(key, label)
    console.print(table)
    console.print(f"[dim]Available MCPs: {', '.join(data['available_mcps'])}[/dim]")


@mcp_app.command("set")
def mcp_set(
    agent: str = typer.Argument(..., help="Agent id (e.g. costaff_agent, coding)"),
    mcps: List[str] = typer.Argument(..., help="MCP server names to assign (space-separated)"),
    no_restart: bool = typer.Option(False, "--no-restart", help="Write config + env only; skip container recreate"),
):
    """Assign the MCP set for one agent (exactly what the dashboard card's save does)."""
    core = active_core()
    key = agent.replace("-", "_")
    try:
        restart = set_agent_mcps(core, key, list(mcps))
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{key} → {', '.join(mcps)}[/green] (core: {core.name})")
    if restart and not no_restart:
        console.print("Recreating the affected container so it reloads the new MCP env...")
        restart()
        console.print("[green]Done.[/green]")
    elif restart:
        console.print("[yellow]Skipped container recreate (--no-restart) — the agent still runs the OLD wiring.[/yellow]")


@agent_app.command("skills")
def agent_skills(name: str = typer.Argument(..., help="External agent name (e.g. coding, twinkle-hub)")):
    """List an external agent's skills from its live A2A card (source of truth)."""
    core = active_core()
    agent = core.core_config().get("external_agents", {}).get(name)
    if not agent:
        console.print(f"[red]Unknown external agent '{name}' on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    try:
        card = fetch_agent_card(agent)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    skills = card.get("skills", [])
    table = Table(title=f"{card.get('name', name)} — {len(skills)} skill(s)  (v{card.get('version', '?')})")
    table.add_column("Skill", style="cyan")
    table.add_column("Description")
    table.add_column("Tags", style="magenta")
    for sk in skills:
        desc = (sk.get("description") or "").split("\n")[0].strip()
        table.add_row(sk.get("name") or sk.get("id") or "?", desc[:100], ", ".join(sk.get("tags", [])))
    console.print(table)
