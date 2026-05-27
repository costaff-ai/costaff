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
import sys
import threading
from typing import Optional

import questionary
import typer
from rich.console import Console

from services.config import ConfigManager
from services.docker import DockerManager
from services.runtime.git import Git, GitError
from utils.paths import _project_root, _base_dir
from utils.deploy import _deploy_local_agent

from .agent import agent_app

console = Console()


def _confirm_enable_transfer(conf: dict, name: str, yes: bool) -> None:
    """Print the global-impact warning for --enable-transfer and gate it.

    Called BEFORE any deploy so declining leaves nothing half-created.
    `-y/--yes` skips the prompt but still prints the warning (audit).
    Non-interactive without `-y` aborts safely (never auto-enables).
    """
    existing = sorted(
        n for n, a in conf.get("external_agents", {}).items()
        if a.get("transfer")
    )
    console.print(
        "\n[yellow]⚠️  --enable-transfer:[/yellow] this agent will be wired "
        "via [bold]transfer (sub_agents)[/bold], not AgentTool.\n\n"
        "  This is NOT local — any transfer agent makes ADK inject the\n"
        "  `transfer_to_agent` tool + sub-agent list into the WHOLE Manager\n"
        "  (global transfer mode, affecting every agent's routing):\n\n"
        "   • transfer carries the conversation/session context (incl.\n"
        "     history) to the sub-agent → it may echo a previous answer or\n"
        "     stay conversational without executing (tested; needs /reset)\n"
        "   • Manager-wide behavior changes; re-run\n"
        "     tests/test_remote_agent_tools.py\n"
        "   • Only enable when this agent needs a transfer-only capability\n"
        "     (e.g. multimodal/image input must reach the sub-agent)\n"
        "   • Reversible: `costaff agent transfer "
        f"{name} --disable` later, no data loss\n\n"
        f"  Agents already on transfer: "
        f"{', '.join(existing) if existing else '(none)'}\n"
    )
    if yes:
        console.print("[dim]--yes: skipping confirmation (transfer enabled).[/dim]")
        return
    if not sys.stdin.isatty():
        console.print(
            "[red]Refusing to enable transfer non-interactively without "
            "`-y/--yes`. Aborting (nothing changed).[/red]"
        )
        raise typer.Exit(1)
    if not questionary.confirm(
        f"Enable transfer for '{name}'?", default=False
    ).ask():
        console.print("[yellow]Aborted — transfer not enabled, nothing changed.[/yellow]")
        raise typer.Exit(1)


@agent_app.command("add")
def agent_add(
    name: str = typer.Argument(..., help="Agent name (e.g. market-analyst)"),
    url: Optional[str] = typer.Option(None, "--url", help="Remote A2A endpoint URL"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path (CoStaff Agent Convention)"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL to clone and deploy"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin --github clone to a release tag, branch, or commit (e.g. v0.1.0-alpha-1). Recorded in config and respected by `agent rebuild`."),
    env: Optional[list[str]] = typer.Option(None, "--env", "-e", help="Set environment variables (e.g. KEY=VALUE)"),
    description: str = typer.Option("", "--description", "-d", help="Short description"),
    strict: bool = typer.Option(False, "--strict", help="Reject the manifest if it does not pass the full Agent Protocol JSON Schema"),
    enable_transfer: bool = typer.Option(False, "--enable-transfer", help="Wire this agent via sub_agents/transfer instead of AgentTool (needed e.g. for multimodal/image input to the sub-agent). Flips the WHOLE Manager into transfer mode — requires confirmation."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive --enable-transfer confirmation (the warning is still printed for audit)."),
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

    # Gate --enable-transfer BEFORE any deploy so declining changes nothing.
    if enable_transfer:
        _confirm_enable_transfer(conf, name, yes)

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
        if tag:
            console.print(f"Cloning [bold cyan]{github}[/bold cyan] @ [bold]{tag}[/bold] to [bold]{target_src}[/bold]...")
        else:
            console.print(f"Cloning [bold cyan]{github}[/bold cyan] to [bold]{target_src}[/bold]...")
        try:
            # Tagged clones need full history so `git checkout` later can
            # move between refs; shallow clone with --branch <tag> works
            # but `agent rebuild --tag <other>` would then fail.
            Git().clone(github, target_src, ref=tag, depth=0 if tag else 1)
            local = target_src
        except GitError as e:
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

    if tag:
        entry["ref"] = tag

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


@agent_app.command("transfer")
def agent_transfer(
    name: str = typer.Argument(..., help="Agent name to toggle transfer wiring for"),
    enable: bool = typer.Option(False, "--enable", help="Wire via sub_agents/transfer (global Manager change — confirmed)"),
    disable: bool = typer.Option(False, "--disable", help="Revert to AgentTool (default, stable contract)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the --enable confirmation (warning still printed)"),
):
    """Toggle an existing agent between AgentTool (default) and transfer.

    The reversible counterpart to `costaff agent add --enable-transfer`.
    config.json's per-agent `transfer` flag is the source of truth;
    `update_external_agents_env()` re-derives COSTAFF_TRANSFER_AGENTS.
    """
    if enable == disable:
        console.print("[red]Specify exactly one of --enable or --disable.[/red]")
        raise typer.Exit(1)
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    entry = conf["external_agents"][name]
    if enable:
        if entry.get("transfer"):
            console.print(f"[yellow]'{name}' is already on transfer. Nothing changed.[/yellow]")
            raise typer.Exit(0)
        _confirm_enable_transfer(conf, name, yes)
        entry["transfer"] = True
    else:
        if not entry.get("transfer"):
            console.print(f"[yellow]'{name}' is already AgentTool (transfer off). Nothing changed.[/yellow]")
            raise typer.Exit(0)
        entry["transfer"] = False
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    state = "transfer (sub_agents)" if enable else "AgentTool (default)"
    console.print(f"[green]'{name}' is now wired via {state}.[/green]")
    console.print("[yellow]Restart costaff-agent-costaff to apply; re-run tests/test_remote_agent_tools.py.[/yellow]")


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
