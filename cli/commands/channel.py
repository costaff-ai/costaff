import os
import re
import shutil
import subprocess
import threading
from typing import Optional, List

import httpx
import questionary
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from managers.config import ConfigManager
from managers.docker import DockerManager
from utils.helpers import PATHS, _project_root
from utils.helpers import _deploy_local_channel  # We'll create this

console = Console()

channel_app = typer.Typer(help="Manage communication channels.")


@channel_app.command("add")
def channel_add(
    name: str = typer.Argument(..., help="Channel name (e.g. webchat)"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL"),
    env: Optional[List[str]] = typer.Option(None, "--env", "-e", help="Set environment variables"),
):
    """Add a communication channel (Local or GitHub mode)."""
    if not local and not github:
        console.print("[red]Error: --local or --github is required[/red]")
        raise typer.Exit(1)
    
    name = name.strip().lower().replace(" ", "-")
    conf = ConfigManager.get_config()
    
    if "dynamic_channels" not in conf:
        conf["dynamic_channels"] = {}

    if name in conf["dynamic_channels"]:
        console.print(f"[red]Error: Channel '{name}' already exists.[/red]")
        raise typer.Exit(1)

    predefined_envs = {}
    if env:
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                predefined_envs[k.strip()] = v.strip()

    if github:
        target_src = os.path.join(_project_root, ".costaff", "src", "channels", name)
        if os.path.exists(target_src):
            if not questionary.confirm(f"Source directory {target_src} already exists. Overwrite?").ask():
                raise typer.Exit(0)
            shutil.rmtree(target_src)
        
        os.makedirs(os.path.dirname(target_src), exist_ok=True)
        console.print(f"Cloning channel [bold cyan]{github}[/bold cyan]...")
        try:
            subprocess.run(["git", "clone", "--depth", "1", github, target_src], check=True)
            local = target_src
        except Exception as e:
            console.print(f"[red]Git clone failed: {e}[/red]")
            raise typer.Exit(1)

    if local:
        try:
            # We'll implement _deploy_local_channel in helpers.py
            entry = _deploy_local_channel(name, local, conf, predefined_envs=predefined_envs)
            conf["dynamic_channels"][name] = entry
            ConfigManager.save_config(conf)
            ConfigManager.update_external_agents_env() # This updates all fragments
            console.print(f"[green]Channel '{name}' deployed and registered.[/green]")
        except Exception as e:
            console.print(f"[red]Deploy failed: {e}[/red]")
            raise typer.Exit(1)


@channel_app.command("list")
def channel_list():
    """List all dynamic communication channels."""
    conf = ConfigManager.get_config()
    channels = conf.get("dynamic_channels", {})
    if not channels:
        console.print("[yellow]No dynamic channels configured.[/yellow]")
        return
    table = Table(title="Dynamic Channels")
    table.add_column("Name", style="cyan")
    table.add_column("Port", justify="center")
    table.add_column("Status", justify="center")
    for name, info in channels.items():
        port = info.get("public_port", "N/A")
        table.add_row(name, str(port), "[green]Active[/green]")
    console.print(table)


@channel_app.command("remove")
def channel_remove(name: str = typer.Argument(...)):
    """Remove a dynamic channel."""
    conf = ConfigManager.get_config()
    if name not in conf.get("dynamic_channels", {}):
        console.print(f"[red]Error: Channel '{name}' not found.[/red]")
        raise typer.Exit(1)
    
    if not questionary.confirm(f"Remove channel '{name}'?").ask():
        return
    
    # Logic to stop containers would go here
    del conf["dynamic_channels"][name]
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Channel '{name}' removed. Restart costaff to apply clean up.[/green]")
