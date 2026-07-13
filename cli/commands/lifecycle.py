import os
import time

import typer
from rich.console import Console

from services.config import ConfigManager
from services.runtime import get_runtime
from services.runtime.process import kill_port

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


def _run_preflight():
    """Validate .env before touching Docker; abort on fatal issues."""
    from services.preflight import check_env

    issues = check_env()
    if not issues:
        return
    fatal = [i for i in issues if i.fatal]
    for i in issues:
        tag = "[red]✖[/red]" if i.fatal else "[yellow]⚠[/yellow]"
        console.print(f"{tag} {i.message}")
        console.print(f"   [dim]→ {i.fix}[/dim]")
    if fatal:
        console.print(
            "\n[red]Aborting — fix the issue(s) above, or re-run with "
            "--no-preflight to skip this check.[/red]"
        )
        raise typer.Exit(1)


def start(
    build: bool = typer.Option(True, "--build/--no-build"),
    preflight: bool = typer.Option(
        True, "--preflight/--no-preflight",
        help="Validate .env (API key, DB URI, secrets) before starting containers.",
    ),
):
    """Start CoStaff services with fine-grained tiered sequence."""
    if preflight:
        _run_preflight()

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

    # Tier 5: Business Platforms (self-contained compose projects).
    # Ordered db → account-manager → rest inside platform_start; failures
    # there never block the core stack.
    if conf.get("platforms"):
        console.print("🚀 [bold]Step 5: Starting Business Platforms...[/bold]")
        from cli.commands.platform import platform_start
        try:
            platform_start(build=False)
        except Exception as e:
            console.print(f"[yellow]Platform start failed ({e}) — core stack is unaffected.[/yellow]")

    console.print(
        "[bold green]SUCCESS: CoStaff started in tiered sequence "
        "(Agents -> Manager -> Channels -> Platforms)![/bold green]"
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

    # Business platforms (separate compose projects, reverse dependency order)
    if conf.get("platforms"):
        from cli.commands.platform import platform_stop
        try:
            platform_stop()
        except Exception as e:
            console.print(f"[yellow]Platform stop failed: {e}[/yellow]")

    # Kill any dashboard process holding port 8501
    kill_port(8501)


def restart():
    """Restart CoStaff services with tiered sequence."""
    console.print("Restarting CoStaff services in sequence...")
    # Preflight BEFORE stop: a fatal .env issue (e.g. a cleared secret) would
    # otherwise abort start() after everything is already stopped, leaving the
    # whole stack down. Validate first so a bad config aborts with the stack
    # still up.
    _run_preflight()
    stop()
    start(build=False, preflight=False)  # already validated above
    console.print("[bold green]SUCCESS: CoStaff restarted in correct sequence![/bold green]")


def core_rebuild(
    no_cache: bool = typer.Option(False, "--no-cache", help="Build images without Docker layer cache"),
):
    """Rebuild manager + core MCP images and cascade-restart plugin agents.

    The sub-agents' ADK MCP sessions hold a TCP connection to costaff-mcp-costaff.
    When that container is replaced (rebuild + recreate) the held session becomes
    stale: ADK keeps the same session handle, partial tool lists leak through, and
    the LLM hallucinates "skill missing" or fabricates task completions. Restarting
    each plugin agent forces ADK to reopen the MCP session against the new container.

    Use after pulling new code that touches manager / mcp-costaff / dispatcher.
    """
    conf = ConfigManager.get_config()
    runtime = get_runtime()

    core_services = ["costaff-agent-costaff", "costaff-mcp-costaff"]

    console.print("[bold]Step 1:[/bold] Building manager core images...")
    runtime.build(core_services, no_cache=no_cache)

    console.print("[bold]Step 2:[/bold] Recreating manager core containers...")
    runtime.up(core_services, force_recreate=True, remove_orphans=False)
    _wait_for_containers(core_services)

    plugin_agents = [
        (name, entry)
        for name, entry in conf.get("external_agents", {}).items()
        if entry.get("enabled") and entry.get("fragment_path") and entry.get("container_names")
    ]
    console.print(
        f"[bold]Step 3:[/bold] Cascading restart to {len(plugin_agents)} plugin agent(s) "
        f"(their MCP session to mcp-costaff is now stale)..."
    )
    for name, entry in plugin_agents:
        console.print(f"  - restarting [cyan]{name}[/cyan]")
        runtime.up(
            entry["container_names"],
            fragment=entry["fragment_path"],
            force_recreate=True,
        )

    console.print("[bold green]SUCCESS: core rebuilt + plugin agents reconnected.[/bold green]")


def status():
    """Check services status."""
    get_runtime().ps()


def logs(service: str = typer.Argument(None)):
    """Show services logs."""
    get_runtime().logs(services=[service] if service else None, tail=100)
