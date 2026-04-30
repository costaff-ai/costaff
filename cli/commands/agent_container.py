"""Agent container ops: list / restart / rebuild.

Inspect or manipulate the Docker containers backing each external agent
without touching the `external_agents` registry — for that, see
agent_lifecycle.

Decorators register against the `agent_app` Typer instance defined in
`cli/commands/agent.py`; that file imports this module so the decorators
fire at startup.
"""
import os
import subprocess

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from services.config import ConfigManager
from services.runtime import get_runtime
from utils.helpers import PATHS

from .agent import agent_app

console = Console()


@agent_app.command("list")
def agent_list():
    """List all external agents with health status."""
    conf = ConfigManager.get_config()
    agents = conf.get("external_agents", {})
    if not agents:
        console.print("[yellow]No external agents configured.[/yellow]")
        return
    table = Table(title="External Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="blue")
    table.add_column("A2A URL")
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    table.add_column("Description")
    for name, agent in agents.items():
        health = "—"
        if agent.get("a2a_url") and agent.get("enabled"):
            try:
                r = httpx.get(f"{agent['a2a_url']}/.well-known/agent-card.json", timeout=3.0)
                health = "[green]●[/green]" if r.status_code == 200 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        table.add_row(name, agent.get("type", "url"), agent.get("a2a_url", ""), health,
                      "✓" if agent.get("enabled") else "✗", (agent.get("description", "") or "")[:50])
    console.print(table)


@agent_app.command("restart")
def agent_restart(name: str = typer.Argument(..., help="Agent name to restart")):
    """Restart a local agent's containers without rebuilding."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"costaff-{name}"])
    load_dotenv(PATHS["env"], override=True)
    runtime = get_runtime()

    console.print(f"Stopping agent [bold]{name}[/bold]...")
    runtime.stop(container_names, fragment=fragment_path)

    console.print(f"Starting agent [bold]{name}[/bold]...")
    try:
        runtime.up(container_names, fragment=fragment_path, force_recreate=True)
        console.print(f"[green]Agent '{name}' restarted.[/green]")
    except subprocess.CalledProcessError:
        console.print(f"[red]Failed to restart agent '{name}'.[/red]")
        raise typer.Exit(1)


@agent_app.command("rebuild")
def agent_rebuild(
    name: str = typer.Argument(..., help="Agent name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Git pull before rebuilding"),
):
    """Rebuild Docker images and restart a local agent from source."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"costaff-{name}"])
    source_path = agent_conf.get("source_path", "(unknown)")
    load_dotenv(PATHS["env"], override=True)
    runtime = get_runtime()

    if pull and os.path.isdir(os.path.join(source_path, ".git")):
        console.print(f"Pulling latest code for [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
        subprocess.run(["git", "pull", "--ff-only"], cwd=source_path)

    console.print(f"Building [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    try:
        runtime.build(container_names, fragment=fragment_path, no_cache=no_cache)
    except RuntimeError:
        console.print(f"[red]Build failed for agent '{name}'.[/red]")
        raise typer.Exit(1)

    console.print(f"Starting rebuilt containers for [bold]{name}[/bold]...")
    try:
        runtime.up(container_names, fragment=fragment_path, force_recreate=True)
        console.print(f"[green]Agent '{name}' rebuilt and restarted.[/green]")
    except subprocess.CalledProcessError:
        console.print(f"[red]Failed to start agent '{name}' after build.[/red]")
        raise typer.Exit(1)
