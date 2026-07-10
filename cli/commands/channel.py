import os
import re
import shutil
import threading
from typing import Optional, List

import httpx
import questionary
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from services.config import ConfigManager
from services.runtime import runtime_for
from services.runtime.git import Git, GitError
from utils.compose import _write_channel_fragment
from utils.deploy import _deploy_local_channel
from .agent_lifecycle import CORE_OPT, _resolve_core

console = Console()

channel_app = typer.Typer(help="Manage communication channels.")


# Official CoStaff Channel Registry
OFFICIAL_CHANNELS = {
    "telegram": "https://github.com/costaff-ai/costaff-channel-telegram.git",
    "line": "https://github.com/costaff-ai/costaff-channel-line.git",
    "discord": "https://github.com/costaff-ai/costaff-channel-discord.git",
    # Canonical repo name is *-oss (renamed on GitHub; the old name only
    # works via redirect, which breaks if the old name is ever reused).
    "webchat": "https://github.com/costaff-ai/costaff-channel-webchat-oss.git",
}


@channel_app.command("add")
def channel_add(
    name: str = typer.Argument(..., help="Channel name (e.g. telegram, webchat)"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin clone to a release tag, branch, or commit (e.g. v0.1.0-alpha-1). Recorded in config and respected by `channel rebuild`."),
    env: Optional[List[str]] = typer.Option(None, "--env", "-e", help="Set environment variables"),
    core_name: Optional[str] = CORE_OPT,
):
    """Add a communication channel (Auto-discovery, Local, or GitHub mode)."""
    name = name.strip().lower().replace(" ", "-")
    core = _resolve_core(core_name)

    # Auto-resolve GitHub URL for official channels if no source is provided
    if not local and not github:
        if name in OFFICIAL_CHANNELS:
            github = OFFICIAL_CHANNELS[name]
            console.print(f"📦 [bold cyan]{name}[/bold cyan] recognized as an official channel.")
        else:
            console.print(f"[red]Error: '{name}' is not an official channel. Please provide --github or --local URL.[/red]")
            raise typer.Exit(1)

    conf = core.core_config()

    if "dynamic_channels" not in conf:
        conf["dynamic_channels"] = {}

    if name in conf["dynamic_channels"]:
        console.print(f"[red]Error: Channel '{name}' already exists on core '{core.name}'.[/red]")
        raise typer.Exit(1)

    predefined_envs = {}
    if env:
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                predefined_envs[k.strip()] = v.strip()

    if github:
        target_src = os.path.join(core.base_dir, "costaff-channel", name, "src")
        if os.path.exists(target_src):
            if not questionary.confirm(f"Source directory {target_src} already exists. Overwrite?").ask():
                raise typer.Exit(0)
            shutil.rmtree(target_src)

        os.makedirs(os.path.dirname(target_src), exist_ok=True)
        if tag:
            console.print(f"Cloning channel [bold cyan]{github}[/bold cyan] @ [bold]{tag}[/bold]...")
        else:
            console.print(f"Cloning channel [bold cyan]{github}[/bold cyan]...")
        try:
            # Tagged clones need full history so `git checkout` can move
            # between refs on rebuild.
            Git().clone(github, target_src, ref=tag, depth=0 if tag else 1)
            local = target_src
        except GitError as e:
            console.print(f"[red]Git clone failed: {e}[/red]")
            raise typer.Exit(1)

    if local:
        try:
            entry = _deploy_local_channel(name, local, conf, predefined_envs=predefined_envs, core=core)
            if tag:
                entry["ref"] = tag
            conf["dynamic_channels"][name] = entry
            core.write_config(conf)
            core.regen_external_agents_env()
            core.regen_mcp_urls()
            console.print(f"[green]Channel '{name}' deployed and registered on core '{core.name}'.[/green]")
        except Exception as e:
            console.print(f"[red]Deploy failed: {e}[/red]")
            raise typer.Exit(1)


@channel_app.command("list")
def channel_list(core_name: Optional[str] = CORE_OPT):
    """List all dynamic communication channels."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    channels = conf.get("dynamic_channels", {})
    if not channels:
        console.print("[yellow]No dynamic channels configured.[/yellow]")
        return
    table = Table(title="Dynamic Channels")
    table.add_column("Name", style="cyan")
    table.add_column("Ref", style="magenta")
    table.add_column("Port", justify="center")
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    for name, info in channels.items():
        port = info.get("public_port")
        health = "—"
        if port and info.get("enabled"):
            try:
                r = httpx.get(f"http://localhost:{port}/.well-known/agent-card.json", timeout=3.0)
                health = "[green]●[/green]" if r.status_code == 200 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        ref = info.get("ref") or "—"
        table.add_row(name, ref, str(port) if port else "N/A", health, "✓" if info.get("enabled") else "✗")
    console.print(table)


@channel_app.command("tags")
def channel_tags(
    name: str = typer.Argument(..., help="Channel name to inspect tags for"),
    core_name: Optional[str] = CORE_OPT,
):
    """List available release tags on the channel's origin remote.

    Use this before `costaff channel rebuild <name> --tag <tag>` to
    discover what versions exist. The currently pinned ref (if any) is
    annotated with ✓.
    """
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("dynamic_channels", {}):
        console.print(f"[red]Error: Channel '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    chan_conf = conf["dynamic_channels"][name]
    source_path = chan_conf.get("source_path")
    if not source_path or not Git().is_repo(source_path):
        console.print(f"[red]Error: No git source for channel '{name}'.[/red]")
        raise typer.Exit(1)

    try:
        tags = Git().list_remote_tags(source_path)
    except GitError as e:
        console.print(f"[red]Failed to query tags: {e}[/red]")
        raise typer.Exit(1)

    pinned = chan_conf.get("ref")
    console.print(f"Available tags for [bold cyan]{name}[/bold cyan]:")
    if not tags:
        console.print("  [yellow](no tags found on origin)[/yellow]")
        return
    for t in tags:
        marker = "  [green]✓ pinned[/green]" if t == pinned else ""
        console.print(f"  {t}{marker}")


@channel_app.command("remove")
def channel_remove(name: str = typer.Argument(...), core_name: Optional[str] = CORE_OPT):
    """Remove a dynamic channel."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("dynamic_channels", {}):
        console.print(f"[red]Error: Channel '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)

    if not questionary.confirm(f"Remove channel '{name}' from core '{core.name}'?").ask():
        return

    chan_conf = conf["dynamic_channels"][name]
    fragment_path = chan_conf.get("fragment_path")
    container_names = chan_conf.get("container_names", [core.cn(f"channel-{name}")])
    runtime = runtime_for(core)

    if fragment_path and os.path.exists(fragment_path):
        console.print(f"Stopping containers for channel [bold]{name}[/bold]...")
        # remove_orphans=False: this fragment only declares the channel being
        # removed; passing True would treat every other fragment's container
        # as an orphan and kill them.
        runtime.down(fragment=fragment_path, remove_orphans=False)
    elif container_names:
        for c in container_names:
            runtime.force_remove_container(c)

    del conf["dynamic_channels"][name]
    core.write_config(conf)
    core.regen_external_agents_env()
    console.print(f"[green]Channel '{name}' stopped and removed from core '{core.name}'.[/green]")


@channel_app.command("rebuild")
def channel_rebuild(
    name: str = typer.Argument(..., help="Channel name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Sync source from origin before rebuilding"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin to a different release tag / branch / commit. Persisted to config."),
    core_name: Optional[str] = CORE_OPT,
):
    """Rebuild Docker images and restart a local channel from source."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("dynamic_channels", {}):
        console.print(f"[red]Error: Channel '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)

    chan_conf = conf["dynamic_channels"][name]
    fragment_path = chan_conf["fragment_path"]
    container_names = chan_conf.get("container_names", [core.cn(f"channel-{name}")])
    source_path = chan_conf.get("source_path", "(unknown)")
    load_dotenv(core.env_path, override=True)

    effective_ref = tag or chan_conf.get("ref")

    git = Git()
    ref_sync_ok = False
    if pull and git.is_repo(source_path):
        if effective_ref:
            console.print(f"Syncing [bold]{name}[/bold] to [bold cyan]{effective_ref}[/bold cyan]...")
            try:
                git.fetch_tags(source_path)
                git.checkout(source_path, effective_ref)
                ref_sync_ok = True
            except GitError as e:
                console.print(f"[yellow]Ref sync failed ({e}); rebuilding with current source.[/yellow]")
        else:
            console.print(f"Pulling latest code for [bold]{name}[/bold]...")
            try:
                git.pull_ff_only(source_path)
            except GitError as e:
                console.print(f"[yellow]Pull failed ({e}); rebuilding with current source.[/yellow]")

    # Persist a new pin only when --tag was explicit AND the checkout
    # actually succeeded (else config would lie about what's on disk).
    if tag and tag != chan_conf.get("ref") and ref_sync_ok:
        chan_conf["ref"] = tag
        core.write_config(conf)

    # Regenerate compose-fragment.yaml from source so any docker-compose.yaml
    # changes (env vars, volumes, etc.) are picked up on rebuild.
    console.print(f"Regenerating compose fragment for [bold]{name}[/bold]...")
    plugin_env_path = os.path.join(core.base_dir, "costaff-channel", name, ".env")
    public_port = chan_conf.get("public_port")
    try:
        fragment_path, ext_services, _ = _write_channel_fragment(
            name, source_path, public_port, plugin_env_path, core=core
        )
        container_names = ext_services
    except Exception as e:
        console.print(f"[yellow]Fragment regenerate failed ({e}); using existing fragment.[/yellow]")

    console.print(f"Building channel [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    runtime = runtime_for(core)
    try:
        runtime.build(container_names, fragment=fragment_path, no_cache=no_cache)
    except RuntimeError:
        console.print(f"[red]Build failed for channel '{name}'.[/red]")
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

    console.print(f"Starting rebuilt channel containers for [bold]{name}[/bold]...")
    try:
        runtime.up(
            container_names,
            fragment=fragment_path,
            force_recreate=True,
            # remove_orphans=False: see channel remove for the same reason —
            # this fragment only knows about the rebuilt channel, so True
            # would kill every other fragment-managed container.
            remove_orphans=False,
        )
        console.print(f"[green]Channel '{name}' rebuilt and restarted.[/green]")
    except RuntimeError as e:
        console.print(f"[red]Failed to start channel '{name}' after build: {e}[/red]")
        raise typer.Exit(1)
