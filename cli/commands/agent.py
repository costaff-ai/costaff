"""`costaff agent ...` command group.

This module owns the shared `agent_app` Typer instance. Concrete commands
live in domain-focused submodules (agent_lifecycle, agent_container,
agent_model). Those modules import `agent_app` from here and decorate
their functions with `@agent_app.command(...)`. We import them at the
bottom of this file so their decorators run when `costaff` boots.
"""
import os
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

from services.config import ConfigManager
from utils.helpers import PATHS

console = Console()

agent_app = typer.Typer(help="Manage external agents.")


# Subcommand modules — each imports `agent_app` from this module and
# registers its own commands via @agent_app.command(...). Imported for
# their decorator side effects.
from . import agent_lifecycle  # noqa: E402,F401  add / remove / enable / disable
from . import agent_container  # noqa: E402,F401  list / restart / rebuild


DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"

# core agent env var (not in config.json external_agents)
_CORE_AGENT = {
    "name": "costaff-agent-costaff",
    "model_env_var": "COSTAFF_AGENT_GEMINI_MODEL",
    "provider_env_var": "COSTAFF_AGENT_MODEL_PROVIDER",
}


def _read_env(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return f.readlines()


def _write_env_key(path: str, key: str, value: str):
    """Update or append a key=value in the .env file."""
    lines = _read_env(path)
    new_line = f"{key}='{value}'\n"
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = new_line
            found = True
            break
    if not found:
        lines.append(new_line)
    with open(path, "w") as f:
        f.writelines(lines)


def _read_env_key(path: str, key: str) -> str:
    for line in _read_env(path):
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            val = stripped.split("=", 1)[1].strip().strip("'\"")
            return val
    return ""


@agent_app.command("model")
def agent_model(
    name: Optional[str] = typer.Argument(None, help="Agent name (omit to set globally for all agents)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Model provider: gemini or litellm"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="LiteLLM API base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="LiteLLM API key"),
    show: bool = typer.Option(False, "--show", help="Show current model settings"),
):
    """Set or view model configuration for an agent."""
    env_path = PATHS["env"]
    conf = ConfigManager.get_config()
    agents = conf.get("external_agents", {})

    # --show: print current settings for all agents
    if show or (not provider and not model and not api_base and not api_key):
        table = Table(title="Model Configuration")
        table.add_column("Agent", style="cyan")
        table.add_column("Provider", style="blue")
        table.add_column("Model")
        table.add_column("LiteLLM API Base")

        global_provider = _read_env_key(env_path, "COSTAFF_AGENT_MODEL_PROVIDER") or "gemini"

        # core agent
        core_provider = _read_env_key(env_path, _CORE_AGENT["provider_env_var"]) or global_provider
        core_model = _read_env_key(env_path, _CORE_AGENT["model_env_var"]) or "gemini-3-flash-preview"
        table.add_row("costaff-agent-costaff (core)", core_provider, core_model, "—")

        for agent_name, agent_conf in agents.items():
            p_var = agent_conf.get("provider_env_var", "")
            m_var = agent_conf.get("model_env_var", "")
            p_val = (_read_env_key(env_path, p_var) if p_var else "") or global_provider
            m_val = (_read_env_key(env_path, m_var) if m_var else "") or "gemini-3-flash-preview"
            api = _read_env_key(env_path, "LITELLM_API_BASE") if p_val == "litellm" else "—"
            table.add_row(agent_name, p_val, m_val, api or "—")

        console.print(table)
        return

    # Determine which agent(s) to configure
    targets: list[dict] = []  # each dict: {name, model_env_var, provider_env_var}

    if name is None:
        # Global: apply to all
        targets.append(_CORE_AGENT)
        for agent_name, agent_conf in agents.items():
            targets.append({
                "name": agent_name,
                "model_env_var": agent_conf.get("model_env_var", ""),
                "provider_env_var": agent_conf.get("provider_env_var", ""),
            })
    elif name == "costaff-agent-costaff":
        targets.append(_CORE_AGENT)
    else:
        if name not in agents:
            console.print(f"[red]Error: Agent '{name}' not found. Use 'costaff agent list' to see available agents.[/red]")
            raise typer.Exit(1)
        a = agents[name]
        targets.append({
            "name": name,
            "model_env_var": a.get("model_env_var", ""),
            "provider_env_var": a.get("provider_env_var", ""),
        })

    # Interactive selection if no flags given
    final_provider = provider
    final_model = model

    if not final_provider:
        final_provider = questionary.select(
            "Select model provider:",
            choices=["gemini", "litellm"],
        ).ask()
        if not final_provider:
            raise typer.Exit(0)

    if final_provider == "gemini" and not final_model:
        final_model = questionary.text(
            "Gemini model name:",
            default=DEFAULT_GEMINI_MODEL,
        ).ask()
        if not final_model:
            raise typer.Exit(0)

    if final_provider == "litellm":
        if not final_model:
            final_model = questionary.text(
                "Enter LiteLLM model name (e.g. openai/gpt-4o):"
            ).ask()
        if not api_base:
            api_base = questionary.text(
                "Enter LiteLLM API base URL:",
                default=_read_env_key(env_path, "LITELLM_API_BASE") or "",
            ).ask()
        if not api_key:
            api_key = questionary.text(
                "Enter LiteLLM API key:",
                default=_read_env_key(env_path, "LITELLM_API_KEY") or "",
            ).ask()

    # Write env vars
    for t in targets:
        if t.get("provider_env_var"):
            _write_env_key(env_path, t["provider_env_var"], final_provider)
        if t.get("model_env_var") and final_model:
            _write_env_key(env_path, t["model_env_var"], final_model)

    if final_provider == "litellm":
        if api_base:
            _write_env_key(env_path, "LITELLM_API_BASE", api_base)
        if api_key:
            _write_env_key(env_path, "LITELLM_API_KEY", api_key)
        if final_model:
            _write_env_key(env_path, "LITELLM_MODEL_NAME", final_model)

    agent_label = name or "all agents"
    console.print(f"[green]Model updated for {agent_label}: provider=[bold]{final_provider}[/bold], model=[bold]{final_model}[/bold][/green]")

    if name and name != "costaff-agent-costaff" and agents.get(name, {}).get("type") == "github":
        console.print(f"[yellow]Run 'costaff agent restart {name}' to apply changes.[/yellow]")
    else:
        console.print("[yellow]Run 'costaff start' or restart the affected agent to apply changes.[/yellow]")


@agent_app.command("rebuild")
def agent_rebuild(
    name: str = typer.Argument(..., help="Agent name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Git pull before rebuilding"),
):
    """Rebuild Docker images and restart a local agent from source."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"costaff-{name}"])
    source_path = agent_conf.get("source_path", "(unknown)")
    load_dotenv(PATHS["env"], override=True)
    runtime = get_runtime()

    if pull and os.path.isdir(os.path.join(source_path, ".git")):
        console.print(f"Pulling latest code for [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
        subprocess.run(["git", "pull", "--ff-only"], cwd=source_path)

    console.print(f"Building [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    try:
        runtime.build(container_names, fragment=fragment_path, no_cache=no_cache)
    except RuntimeError:
        console.print(f"[red]Build failed for agent '{name}'.[/red]")
        raise typer.Exit(1)

    console.print(f"Starting rebuilt containers for [bold]{name}[/bold]...")
    try:
        runtime.up(container_names, fragment=fragment_path, force_recreate=True)
        console.print(f"[green]Agent '{name}' rebuilt and restarted.[/green]")
    except subprocess.CalledProcessError:
        console.print(f"[red]Failed to start agent '{name}' after build.[/red]")
        raise typer.Exit(1)
