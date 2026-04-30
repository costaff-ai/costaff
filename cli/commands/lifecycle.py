import os
import subprocess
import time

import typer
from rich.console import Console

from managers.config import ConfigManager
from managers.runtime import get_runtime

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
    runtime.up(core_services, build=build, remove_orphans=True)
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
    """Stop all services."""
    runtime = get_runtime()
    runtime.down(remove_orphans=True)
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
