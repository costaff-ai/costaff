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
from utils.helpers import PATHS, _project_root, _runtime_root
from utils.helpers import _deploy_local_channel, _write_channel_fragment

console = Console()

channel_app = typer.Typer(help="Manage communication channels.")


# Official CoStaff Channel Registry
OFFICIAL_CHANNELS = {
    "telegram": "https://github.com/costaff-ai/costaff-channel-telegram.git",
    "line": "https://github.com/costaff-ai/costaff-channel-line.git",
    "discord": "https://github.com/costaff-ai/costaff-channel-discord.git",
    "webchat": "https://github.com/costaff-ai/costaff-channel-webchat.git",
}


@channel_app.command("add")
def channel_add(
    name: str = typer.Argument(..., help="Channel name (e.g. telegram, webchat)"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL"),
    env: Optional[List[str]] = typer.Option(None, "--env", "-e", help="Set environment variables"),
):
    """Add a communication channel (Auto-discovery, Local, or GitHub mode)."""
    name = name.strip().lower().replace(" ", "-")
    
    # Auto-resolve GitHub URL for official channels if no source is provided
    if not local and not github:
        if name in OFFICIAL_CHANNELS:
            github = OFFICIAL_CHANNELS[name]
            console.print(f"📦 [bold cyan]{name}[/bold cyan] recognized as an official channel.")
        else:
            console.print(f"[red]Error: '{name}' is not an official channel. Please provide --github or --local URL.[/red]")
            raise typer.Exit(1)
    
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
        target_src = os.path.join(_runtime_root, "src", "channels", name)
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
            ConfigManager.update_external_agents_env()
            ConfigManager.update_mcp_urls()
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
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    for name, info in channels.items():
        port = info.get("public_port")
        health = "—"
        if port and info.get("enabled"):
            try:
                r = httpx.get(f"http://localhost:{port}/.well-known/agent.json", timeout=3.0)
                health = "[green]●[/green]" if r.status_code == 200 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        table.add_row(name, str(port) if port else "N/A", health, "✓" if info.get("enabled") else "✗")
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

    chan_conf = conf["dynamic_channels"][name]
    fragment_path = chan_conf.get("fragment_path")
    container_names = chan_conf.get("container_names", [f"costaff-channel-{name}"])
    main_compose = os.path.join(_runtime_root, "docker-compose.yaml")

    if fragment_path and os.path.exists(fragment_path):
        console.print(f"Stopping containers for channel [bold]{name}[/bold]...")
        stop_cmd = DockerManager.get_cmd() + [
            "-f", main_compose, "-f", fragment_path, "down", "--remove-orphans"
        ]
        subprocess.run(stop_cmd, check=False, cwd=_project_root)
    elif container_names:
        for c in container_names:
            subprocess.run(["docker", "stop", c], capture_output=True)
            subprocess.run(["docker", "rm", c], capture_output=True)

    del conf["dynamic_channels"][name]
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Channel '{name}' stopped and removed.[/green]")


@channel_app.command("rebuild")
def channel_rebuild(
    name: str = typer.Argument(..., help="Channel name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Git pull before rebuilding"),
):
    """Rebuild Docker images and restart a local channel from source."""
    conf = ConfigManager.get_config()
    if name not in conf.get("dynamic_channels", {}):
        console.print(f"[red]Error: Channel '{name}' not found.[/red]")
        raise typer.Exit(1)

    chan_conf = conf["dynamic_channels"][name]
    fragment_path = chan_conf["fragment_path"]
    container_names = chan_conf.get("container_names", [f"costaff-channel-{name}"])
    source_path = chan_conf.get("source_path", "(unknown)")
    main_compose = os.path.join(_runtime_root, "docker-compose.yaml")
    load_dotenv(PATHS["env"], override=True)

    if pull and os.path.isdir(os.path.join(source_path, ".git")):
        console.print(f"Pulling latest code for [bold]{name}[/bold]...")
        subprocess.run(["git", "pull", "--ff-only"], cwd=source_path)

    # Regenerate compose-fragment.yaml from source so any docker-compose.yaml
    # changes (env vars, volumes, etc.) are picked up on rebuild.
    console.print(f"Regenerating compose fragment for [bold]{name}[/bold]...")
    plugin_env_path = os.path.join(_runtime_root, "dynamic-channels", name, ".env")
    public_port = chan_conf.get("public_port")
    try:
        fragment_path, ext_services, _ = _write_channel_fragment(
            name, source_path, public_port, plugin_env_path
        )
        container_names = ext_services
    except Exception as e:
        console.print(f"[yellow]Fragment regenerate failed ({e}); using existing fragment.[/yellow]")

    console.print(f"Building channel [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    build_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "build"]
    if no_cache:
        build_cmd.append("--no-cache")
    build_cmd.extend(container_names)

    build_result = subprocess.run(build_cmd, cwd=_project_root)
    if build_result.returncode != 0:
        console.print(f"[red]Build failed for channel '{name}'.[/red]")
        raise typer.Exit(1)

    console.print(f"Starting rebuilt channel containers for [bold]{name}[/bold]...")
    up_result = subprocess.run(
        DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path,
                                   "up", "-d", "--force-recreate", "--remove-orphans"] + container_names,
        cwd=_project_root,
    )
    if up_result.returncode == 0:
        console.print(f"[green]Channel '{name}' rebuilt and restarted.[/green]")
    else:
        console.print(f"[red]Failed to start channel '{name}' after build.[/red]")
        raise typer.Exit(1)
