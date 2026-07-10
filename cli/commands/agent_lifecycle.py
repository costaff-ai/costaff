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
from typing import Optional

import questionary
import typer
from rich.console import Console

from services.cores import get_core
from services.runtime import runtime_for
from services.runtime.git import Git, GitError
from utils.paths import _project_root
from utils.deploy import _deploy_local_agent

from .agent import agent_app

console = Console()

CORE_OPT = typer.Option(None, "--core", help="Target core (see `costaff core list`). Default: the active core.")


def _resolve_core(name):
    """--core resolution shared by every agent command."""
    # When a command function is invoked directly in Python (e.g. the
    # `update --all` fan-out) rather than through Typer, an unset --core
    # arrives as the OptionInfo sentinel, not None. Treat any non-string as
    # "unset" so it resolves to the active core instead of raising.
    if not isinstance(name, str):
        name = None
    try:
        return get_core(name)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


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
    core_name: Optional[str] = CORE_OPT,
):
    """Add an external agent (URL, Local, or GitHub mode)."""
    if not url and not local and not github:
        console.print("[red]Error: --url, --local, or --github is required[/red]")
        raise typer.Exit(1)

    name = name.strip().lower().replace(" ", "-")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', name):
        console.print("[red]Error: name must be lowercase alphanumeric with hyphens/underscores[/red]")
        raise typer.Exit(1)

    core = _resolve_core(core_name)
    if not core.is_default:
        console.print(f"[dim]Target core: {core.name} ({core.label})[/dim]")
    conf = core.core_config()
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
        target_src = os.path.join(core.base_dir, "costaff-agent", name, "src")
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
                name, local, conf, predefined_envs=predefined_envs, strict=strict, core=core
            )
        except Exception as e:
            console.print(f"[red]Deploy failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        # added_by stamps CRUD ownership: CLI-added agents are only removable
        # via `costaff agent remove` (the dashboard rejects them).
        entry = {"type": "url", "added_by": "cli", "a2a_url": url, "description": description, "enabled": True}

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

        # Do NOT add this MCP to the manager (agent_mcps.costaff_agent). The
        # manager reaches specialists via A2A AgentTool, not via their MCP;
        # loading N streamable MCPs into the manager triggers the ADK anyio
        # cancel-scope race (see services/config.update_mcp_urls, which warns
        # about exactly this). Keep the manager on its own MCP only; operators
        # who really want a sub-agent's tools in the manager can edit
        # config.json → agent_mcps.costaff_agent by hand.
        am.setdefault("costaff_agent", ["costaff"])

        # Ensure Specialist can see its own tools + core tools
        if agent_key not in am:
            am[agent_key] = ["costaff", name]

        # 3. Seed the core-tool whitelist. Without it the sub-agent inherits
        # the manager's full ~40-tool MCP spec → token bloat on every LLM
        # call + tool mis-selection. Seed only if absent so operators can
        # customise config.json afterwards.
        from services.config import CORE_PLUGIN_MCP_TOOLS
        filters = conf.setdefault("agent_mcp_filters", {})
        if agent_key not in filters:
            filters[agent_key] = {"costaff": list(CORE_PLUGIN_MCP_TOOLS)}
            console.print(
                f"[dim]Whitelisted the 4 core MCP tools for '{name}' "
                f"(edit config.json → agent_mcp_filters.{agent_key} to change).[/dim]"
            )

    core.write_config(conf)
    core.regen_external_agents_env()
    core.regen_mcp_urls()

    console.print(f"[green]Agent '{name}' deployed and registered on core '{core.name}'.[/green]")
    console.print("Recreating the manager so it picks up the new agent...")
    core.recreate_manager()
    console.print("[green]Done.[/green]")


@agent_app.command("remove")
def agent_remove(
    name: str = typer.Argument(..., help="Agent name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt (non-interactive use)"),
    core_name: Optional[str] = CORE_OPT,
):
    """Remove an external agent."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    if not yes and not questionary.confirm(f"Remove agent '{name}' from core '{core.name}'?").ask():
        return

    # Stop and remove the agent's containers BEFORE dropping its config entry —
    # otherwise the container keeps running and holds its host port, and the
    # next `agent add` reuses that (now-free-in-config) port and fails to bind.
    # Mirrors `channel remove` / `platform remove`. (url-type agents have no
    # fragment/containers — nothing to stop.)
    entry = conf["external_agents"][name]
    fragment_path = entry.get("fragment_path")
    container_names = entry.get("container_names", [])
    try:
        runtime = runtime_for(core)
        if fragment_path and os.path.exists(fragment_path):
            console.print(f"Stopping containers for agent [bold]{name}[/bold]...")
            # remove_orphans=False: this fragment only declares the agent being
            # removed; True would treat every other plugin's container as an
            # orphan and kill them.
            runtime.down(fragment=fragment_path, remove_orphans=False)
        else:
            for c in container_names:
                runtime.force_remove_container(c)
    except Exception as e:
        # Don't strand the config entry if teardown hiccups — warn and proceed
        # so the user isn't left with a half-removed agent they can't retry.
        console.print(f"[yellow]Warning: could not fully stop containers for '{name}': {e}[/yellow]")
        console.print(f"[yellow]Check `docker ps` for leftover {core.prefix}-*-{name} containers.[/yellow]")

    del conf["external_agents"][name]
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = False

    # Tear down the MCP wiring `agent add` created for a configurable agent —
    # otherwise the dead MCP lingers in `mcp` / `agent_mcps` / `agent_mcp_filters`
    # and the next `update_mcp_urls` (costaff start, or the next agent add)
    # regenerates a URL for the removed `<prefix>-mcp-<name>` container and
    # feeds it back into the manager env.
    agent_key = name.replace("-", "_")
    if name in conf.get("mcp", []):
        conf["mcp"].remove(name)
    am = conf.get("agent_mcps", {})
    am.pop(agent_key, None)
    # Defensive: drop the name from the manager's list too, in case an older
    # `agent add` (pre-fix) had appended it there.
    if name in am.get("costaff_agent", []):
        am["costaff_agent"].remove(name)
    conf.get("agent_mcp_filters", {}).pop(agent_key, None)

    core.write_config(conf)
    core.regen_external_agents_env()
    core.regen_mcp_urls()
    core.recreate_manager()
    console.print(f"[green]Agent '{name}' stopped and removed from core '{core.name}'.[/green]")


@agent_app.command("enable")
def agent_enable(name: str = typer.Argument(...), core_name: Optional[str] = CORE_OPT):
    """Enable an external agent."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = True
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = True
    core.write_config(conf)
    core.regen_external_agents_env()
    core.recreate_manager()
    console.print(f"[green]Agent '{name}' enabled on core '{core.name}'.[/green]")


@agent_app.command("transfer")
def agent_transfer(
    name: str = typer.Argument(..., help="Agent name to toggle transfer wiring for"),
    enable: bool = typer.Option(False, "--enable", help="Wire via sub_agents/transfer (global Manager change — confirmed)"),
    disable: bool = typer.Option(False, "--disable", help="Revert to AgentTool (default, stable contract)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the --enable confirmation (warning still printed)"),
    core_name: Optional[str] = CORE_OPT,
):
    """Toggle an existing agent between AgentTool (default) and transfer.

    The reversible counterpart to `costaff agent add --enable-transfer`.
    config.json's per-agent `transfer` flag is the source of truth;
    `update_external_agents_env()` re-derives COSTAFF_TRANSFER_AGENTS.
    """
    if enable == disable:
        console.print("[red]Specify exactly one of --enable or --disable.[/red]")
        raise typer.Exit(1)
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
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
    core.write_config(conf)
    core.regen_external_agents_env()
    core.recreate_manager()
    state = "transfer (sub_agents)" if enable else "AgentTool (default)"
    console.print(f"[green]'{name}' is now wired via {state} (Manager recreated).[/green]")


@agent_app.command("disable")
def agent_disable(name: str = typer.Argument(...), core_name: Optional[str] = CORE_OPT):
    """Disable an external agent."""
    core = _resolve_core(core_name)
    conf = core.core_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found on core '{core.name}'.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = False
    if name == "costaff-agent-coding":
        conf["coding_agent_enabled"] = False
    core.write_config(conf)
    core.regen_external_agents_env()
    core.recreate_manager()
    console.print(f"[green]Agent '{name}' disabled on core '{core.name}'.[/green]")
