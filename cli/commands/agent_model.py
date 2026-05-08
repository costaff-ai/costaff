"""`costaff agent model` — view and set per-agent LLM model configuration.

Each agent declares two env vars in its config.json entry:
  - `provider_env_var` — e.g. `CODING_AGENT_MODEL_PROVIDER`
  - `model_env_var`    — e.g. `CODING_AGENT_MODEL`

This command reads/writes them in the core .env file. The core agent
(costaff-agent-costaff) doesn't appear in `external_agents`, so its env
vars are hard-coded in `_CORE_AGENT`.

Decorators register against the `agent_app` Typer instance defined in
`cli/commands/agent.py`.
"""
import os
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

from services.config import ConfigManager
from utils.paths import PATHS

from .agent import agent_app

console = Console()

DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"

# Core agent isn't in config.json's external_agents — its env-var names
# are fixed and known here so `agent model` (with no name) can sweep it.
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
