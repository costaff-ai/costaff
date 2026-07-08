"""Agent container ops: list / restart / rebuild.

Inspect or manipulate the Docker containers backing each external agent
without touching the `external_agents` registry — for that, see
agent_lifecycle.

Decorators register against the `agent_app` Typer instance defined in
`cli/commands/agent.py`; that file imports this module so the decorators
fire at startup.
"""
import os
from typing import Optional

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from services.agent_components import agent_card_url
from services.runtime import runtime_for
from services.runtime.git import Git, GitError

from .agent import agent_app
from .agent_lifecycle import CORE_OPT, _resolve_core

console = Console()


@agent_app.command("list")
def agent_list(core_name: Optional[str] = CORE_OPT):
    """List all external agents with health status."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    agents = conf.get("external_agents", {})
    if not agents:
        console.print(f"[yellow]No external agents configured on core '{core.name}'.[/yellow]")
        return
    table = Table(title=f"External Agents (core: {core.name})")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="blue")
    table.add_column("Ref", style="magenta")
    table.add_column("A2A URL")
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    table.add_column("Description")
    for name, agent in agents.items():
        health = "—"
        # Host-side reachable URL (github → localhost:public_port), same
        # resolution as the dashboard health check.
        probe = agent_card_url(agent)
        if probe and agent.get("enabled"):
            try:
                r = httpx.get(f"{probe}/.well-known/agent-card.json", timeout=3.0)
                health = "[green]●[/green]" if r.status_code == 200 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        ref = agent.get("ref") or "—"
        table.add_row(name, agent.get("type", "url"), ref, agent.get("a2a_url", ""), health,
                      "✓" if agent.get("enabled") else "✗", (agent.get("description", "") or "")[:50])
    console.print(table)


@agent_app.command("tags")
def agent_tags(
    name: str = typer.Argument(..., help="Agent name to inspect tags for"),
    core_name: Optional[str] = CORE_OPT,
):
    """List available release tags on the agent's origin remote.

    Use this to discover what versions exist before pinning via
    `costaff agent rebuild <name> --tag <tag>`. Tags are queried via
    `git ls-remote` against the existing local clone's origin URL, so
    no fetch is required and the network round-trip is light. The
    currently pinned ref (if any) is annotated with a ✓ mark.
    """
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    source_path = agent_conf.get("source_path")
    if not source_path or not Git().is_repo(source_path):
        console.print(f"[red]Error: No git source for agent '{name}' (type={agent_conf.get('type')}).[/red]")
        raise typer.Exit(1)

    try:
        tags = Git().list_remote_tags(source_path)
    except GitError as e:
        console.print(f"[red]Failed to query tags: {e}[/red]")
        raise typer.Exit(1)

    pinned = agent_conf.get("ref")
    console.print(f"Available tags for [bold cyan]{name}[/bold cyan]:")
    if not tags:
        console.print("  [yellow](no tags found on origin)[/yellow]")
        return
    for t in tags:
        marker = "  [green]✓ pinned[/green]" if t == pinned else ""
        console.print(f"  {t}{marker}")


@agent_app.command("restart")
def agent_restart(
    name: str = typer.Argument(..., help="Agent name to restart"),
    core_name: Optional[str] = CORE_OPT,
):
    """Restart a local agent's containers without rebuilding."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"{core.prefix}-{name}"])
    load_dotenv(core.env_path, override=True)
    runtime = runtime_for(core)

    console.print(f"Stopping agent [bold]{name}[/bold]...")
    runtime.stop(container_names, fragment=fragment_path)

    console.print(f"Starting agent [bold]{name}[/bold]...")
    try:
        runtime.up(container_names, fragment=fragment_path, force_recreate=True)
        console.print(f"[green]Agent '{name}' restarted.[/green]")
    except RuntimeError as e:
        console.print(f"[red]Failed to restart agent '{name}': {e}[/red]")
        raise typer.Exit(1)


@agent_app.command("rebuild")
def agent_rebuild(
    name: str = typer.Argument(..., help="Agent name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Sync source from origin before rebuilding (pull for branch pin, fetch+checkout for tag/commit pin)"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin to a different release tag / branch / commit. Persisted to config so the next rebuild stays on this ref."),
    core_name: Optional[str] = CORE_OPT,
):
    """Rebuild Docker images and restart a local agent from source."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"{core.prefix}-{name}"])
    source_path = agent_conf.get("source_path", "(unknown)")
    load_dotenv(core.env_path, override=True)
    runtime = runtime_for(core)

    # Effective ref: --tag overrides any persisted pin; otherwise stay on
    # whatever the entry has. None means "track default branch" — same as
    # the historical pre-tag behaviour.
    effective_ref = tag or agent_conf.get("ref")

    git = Git()
    ref_sync_ok = False
    if pull and git.is_repo(source_path):
        if effective_ref:
            console.print(f"Syncing [bold]{name}[/bold] to [bold cyan]{effective_ref}[/bold cyan] in [cyan]{source_path}[/cyan]...")
            try:
                git.fetch_tags(source_path)
                git.checkout(source_path, effective_ref)
                ref_sync_ok = True
            except GitError as e:
                console.print(f"[yellow]Ref sync failed ({e}); rebuilding with current source.[/yellow]")
        else:
            console.print(f"Pulling latest code for [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
            try:
                git.pull_ff_only(source_path)
            except GitError as e:
                console.print(f"[yellow]Pull failed ({e}); rebuilding with current source.[/yellow]")

    # Persist a new pin only when --tag was explicit AND the checkout
    # actually succeeded. Otherwise we'd lie in config.json about what's
    # on disk — the operator would see "ref: v0.1.0-alpha-1" but the
    # source tree would still be on whatever ref it was before.
    if tag and tag != agent_conf.get("ref") and ref_sync_ok:
        agent_conf["ref"] = tag
        core.write_config(conf)

    console.print(f"Building [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    try:
        runtime.build(container_names, fragment=fragment_path, no_cache=no_cache)
    except RuntimeError:
        console.print(f"[red]Build failed for agent '{name}'.[/red]")
        raise typer.Exit(1)

    # Remove any existing containers by name before `up`. compose's
    # --force-recreate only recovers containers in the SAME project
    # label; a container created under a different project keeps its
    # name and blocks the new container with a name-conflict error.
    # force_remove_container is idempotent — no-op if the name is unused.
    if container_names:
        console.print(f"Removing any old containers: [dim]{', '.join(container_names)}[/dim]")
        for cname in container_names:
            runtime.force_remove_container(cname)

    console.print(f"Starting rebuilt containers for [bold]{name}[/bold]...")
    try:
        runtime.up(container_names, fragment=fragment_path, force_recreate=True)
        console.print(f"[green]Agent '{name}' rebuilt and restarted.[/green]")
    except RuntimeError as e:
        console.print(f"[red]Failed to start agent '{name}' after build: {e}[/red]")
        raise typer.Exit(1)
