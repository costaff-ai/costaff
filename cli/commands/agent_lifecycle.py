"""Agent lifecycle commands: add / remove / enable / disable.

These commands mutate `config.json`'s `external_agents` registry — `add`
also deploys a new agent (local source / GitHub clone / remote URL).

Decorators register against the `agent_app` Typer instance defined in
`cli/commands/agent.py`; that file imports this module at the bottom so
the decorators fire and the commands appear under `costaff agent ...`.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Optional

import questionary
import typer
from rich.console import Console

from services.config import ConfigManager
from services.docker import DockerManager
from utils.helpers import _project_root, _base_dir, _deploy_local_agent

from .agent import agent_app

console = Console()


@agent_app.command("add")
def agent_add(
    name: str = typer.Argument(..., help="Agent name (e.g. market-analyst)"),
    url: Optional[str] = typer.Option(None, "--url", help="Remote A2A endpoint URL"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path (CoStaff Agent Convention)"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL to clone and deploy"),
    env: Optional[list[str]] = typer.Option(None, "--env", "-e", help="Set environment variables (e.g. KEY=VALUE)"),
    description: str = typer.Option("", "--description", "-d", help="Short description"),
    strict: bool = typer.Option(False, "--strict", help="Reject the manifest if it does not pass the full Agent Protocol JSON Schema"),
):
    """Add an external agent (URL, Local, or GitHub mode)."""
    if not url and not local and not github:
        console.print("[red]Error: --url, --local, or --github is required[/red]")
        raise typer.Exit(1)

    name = name.strip().lower().replace(" ", "-")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', name):
        console.print("[red]Error: name must be lowercase alphanumeric with hyphens/underscores[/red]")
        raise typer.Exit(1)

    conf = ConfigManager.get_config()
    if name in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' already exists. Use 'costaff agent remove {name}' first.[/red]")
        raise typer.Exit(1)

    # License check. Each CLI invocation is a fresh process, so the
    # in-memory `_license` cache is None until `load()` is called —
    # without it, `check_agent_limit()` would fall back to OSS limits
    # even on ENTERPRISE plans.
    try:
        sys.path.insert(0, _project_root)
        from core.license import LicenseManager
        LicenseManager.load()
        current_count = len([a for a in conf.get("external_agents", {}).values() if a.get("enabled")])
        LicenseManager.check_agent_limit(current_count)
    except ValueError as e:
        console.print(f"[red]✖ {e}[/red]")
        raise typer.Exit(1)

    # Parse provided env vars
    predefined_envs = {}
    if env:
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                predefined_envs[k.strip()] = v.strip()

    if github:
        target_src = os.path.join(_base_dir, "costaff-agent", name, "src")
        if os.path.exists(target_src):
            if sys.stdin.isatty() and not questionary.confirm(f"Source directory {target_src} already exists. Overwrite?").ask():
                raise typer.Exit(0)
            shutil.rmtree(target_src)

        os.makedirs(os.path.dirname(target_src), exist_ok=True)
        console.print(f"Cloning [bold cyan]{github}[/bold cyan] to [bold]{target_src}[/bold]...")
        try:
            subprocess.run(["git", "clone", "--depth", "1", github, target_src], check=True)
            local = target_src
        except Exception as e:
            console.print(f"[red]Git clone failed: {e}[/red]")
            raise typer.Exit(1)

    if local:
        try:
            entry = _deploy_local_agent(
                name, local, conf, predefined_envs=predefined_envs, strict=strict
            )
        except Exception as e:
            console.print(f"[red]Deploy failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        entry = {"type": "url", "a2a_url": url, "description": description, "enabled": True}

    conf.setdefault("external_agents", {})[name] = entry

    # Auto-register MCP if configurable
    if entry.get("mcp_configurable"):
        # 1. Add to master MCP list if not there
        if name not in conf.get("mcp", []):
            conf.setdefault("mcp", []).append(name)

        # 2. Setup default agent_mcps mapping
        agent_key = name.replace("-", "_")
        am = conf.setdefault("agent_mcps", {})

        # Ensure Root Agent can see this new specialist's tools
        if "costaff_agent" not in am:
            am["costaff_agent"] = ["costaff"]
        if name not in am["costaff_agent"]:
            am["costaff_agent"].append(name)

        # Ensure Specialist can see its own tools + core tools
        if agent_key not in am:
            am[agent_key] = ["costaff", name]

    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    ConfigManager.update_mcp_urls()

    console.print(f"[green]Agent '{name}' deployed and registered.[/green]")
    console.print("Restarting core agent to apply changes...")
    threading.Thread(target=DockerManager.run_action, args=("costaff-agent-costaff", "restart"), daemon=False).start()
    console.print("[green]Done.[/green]")


@agent_app.command("remove")
def agent_remove(name: str = typer.Argument(..., help="Agent name to remove")):
    """Remove an external agent."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    if not questionary.confirm(f"Remove agent '{name}'?").ask():
        return
    del conf["external_agents"][name]
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = False
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' removed.[/green]")
    console.print("[yellow]Restart costaff-agent-costaff to apply: costaff start[/yellow]")


@agent_app.command("enable")
def agent_enable(name: str = typer.Argument(...)):
    """Enable an external agent."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = True
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = True
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' enabled.[/green]")
    console.print("[yellow]Restart costaff-agent-costaff to apply changes.[/yellow]")


@agent_app.command("disable")
def agent_disable(name: str = typer.Argument(...)):
    """Disable an external agent."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = False
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = False
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' disabled.[/green]")
    console.print("[yellow]Restart costaff-agent-costaff to apply changes.[/yellow]")
