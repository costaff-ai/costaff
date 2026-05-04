import os
import subprocess
import time

import typer
from rich.console import Console

from services.config import ConfigManager
from services.runtime import get_runtime

console = Console()


def _wait_for_containers(container_names: list, timeout: int = 30):
    """Wait for the given containers to all be running, up to `timeout` seconds."""
    if not container_names:
        return
    runtime = get_runtime()
    console.print(f"Waiting for {len(container_names)} services to initialize...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        states = runtime.is_running(container_names)
        if states and all(states.values()):
            time.sleep(5)  # let internal app startup settle
            return
        time.sleep(2)
    console.print("[yellow]Warning: Some services may still be initializing.[/yellow]")


def start(build: bool = typer.Option(True, "--build/--no-build")):
    """Start CoStaff services with fine-grained tiered sequence."""
    conf = ConfigManager.get_config()
    runtime = get_runtime()

    ConfigManager.update_mcp_urls()

    # Tier 1: Infrastructure (Postgres)
    console.print("🚀 [bold]Step 1: Starting Infrastructure (Postgres)...[/bold]")
    runtime.up(["postgres"])

    # Tier 2: External Agents
    agent_containers = []
    for name, entry in conf.get("external_agents", {}).items():
        if not entry.get("enabled"):
            continue
        fragment_path = entry.get("fragment_path")
        container_names = entry.get("container_names", [])
        if fragment_path and container_names:
            console.print(f"🚀 [bold]Step 2: Starting External Agent {name}...[/bold]")
            runtime.up(container_names, fragment=fragment_path, build=build)
            agent_containers.extend(container_names)

    if agent_containers:
        _wait_for_containers(agent_containers)

    # Tier 3: Core Agent (the manager) + Core MCP
    console.print("🚀 [bold]Step 3: Starting CoStaff Manager...[/bold]")
    core_services = ["costaff-agent-costaff", "costaff-mcp-costaff"]
    # remove_orphans must stay False — Tier 2 external-agent containers live in
    # separate fragments and would look like orphans to the main compose,
    # which would silently kill the agents we just started.
    runtime.up(core_services, build=build, remove_orphans=False)
    _wait_for_containers(core_services)

    # Tier 4: Dynamic Channels
    for name, entry in conf.get("dynamic_channels", {}).items():
        if not entry.get("enabled"):
            continue
        fragment_path = entry.get("fragment_path")
        container_names = entry.get("container_names", [])
        if fragment_path and container_names:
            console.print(f"🚀 [bold]Step 4: Starting Channel {name}...[/bold]")
            runtime.up(container_names, fragment=fragment_path, build=build)

    console.print(
        "[bold green]SUCCESS: CoStaff started in tiered sequence "
        "(Agents -> Manager -> Channels)![/bold green]"
    )


def stop():
    """Stop all services — iterate fragments + main, no orphan hammer."""
    runtime = get_runtime()
    conf = ConfigManager.get_config()

    # Collect channel + external-agent fragments. Iterating with
    # docker-compose-down per-fragment lets us tear each one down safely
    # without `--remove-orphans`, which would silently kill containers
    # belonging to OTHER fragments (the same bug we hit in `start` and
    # `channel rebuild`).
    fragments: list[str] = []
    for entry in conf.get("dynamic_channels", {}).values():
        fp = entry.get("fragment_path")
        if fp and os.path.exists(fp):
            fragments.append(fp)
    for entry in conf.get("external_agents", {}).values():
        fp = entry.get("fragment_path")
        if fp and os.path.exists(fp):
            fragments.append(fp)

    for fp in fragments:
        try:
            runtime.down(fragment=fp, remove_orphans=False)
        except Exception as e:
            console.print(f"[yellow]Failed to stop fragment {fp}: {e}[/yellow]")

    # Final pass on the main compose. Each fragment-down already brought
    # main services down (compose loads main + fragment together), so this
    # is idempotent in practice — but it ensures cleanup if a deployment
    # has no fragments at all.
    try:
        runtime.down(remove_orphans=False)
    except Exception as e:
        console.print(f"[yellow]Failed to stop core compose: {e}[/yellow]")

    # Kill any dashboard process holding port 8501
    try:
        result = subprocess.run(["lsof", "-ti", ":8501"], capture_output=True, text=True)
        for pid in result.stdout.strip().split():
            if pid:
                subprocess.run(["kill", pid], capture_output=True)
    except Exception:
        pass


def restart():
    """Restart CoStaff services with tiered sequence."""
    console.print("Restarting CoStaff services in sequence...")
    stop()
    start(build=False)
    console.print("[bold green]SUCCESS: CoStaff restarted in correct sequence![/bold green]")


def status():
    """Check services status."""
    get_runtime().ps()


def logs(service: str = typer.Argument(None)):
    """Show services logs."""
    get_runtime().logs(services=[service] if service else None, tail=100)
