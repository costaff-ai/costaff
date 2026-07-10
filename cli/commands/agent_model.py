"""`costaff agent model` — view and set per-agent LLM model configuration.

Write targets differ by agent kind:
  - core agent (costaff-agent-costaff): env vars live in the CORE .env
    (compose `env_file: - .env`); names hard-coded in `_CORE_AGENT`.
  - external agents: env vars live in the PLUGIN .env next to the compose
    fragment. The fragment wires `env_file: [core .env, plugin .env]` with
    the plugin file LAST, so it wins — writing the core .env for these
    agents is a silent no-op (the historical bug this module regressed on).

The env-var names come from the agent's config.json entry
(`model_env_var` / `provider_env_var`, recorded by `agent add`); entries
created before v0.1.0 lack them, so we recover the name from the agent's
manifest on disk.

Decorators register against the `agent_app` Typer instance defined in
`cli/commands/agent.py`.
"""
import json
import os
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

from .agent import agent_app
from .agent_lifecycle import CORE_OPT, _resolve_core

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
    """Update or append a key=value in the .env file.

    No quotes: docker compose's env_file parser hands single-quoted values
    through literally (see services/config.py) — same reason every other
    .env writer in the repo uses set_key(quote_mode="never").
    """
    lines = _read_env(path)
    new_line = f"{key}={value}\n"
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


def _plugin_env_path(agent_conf: dict) -> str:
    """The plugin .env next to the agent's compose fragment ('' if none)."""
    frag = agent_conf.get("fragment_path", "")
    return os.path.join(os.path.dirname(frag), ".env") if frag else ""


def _model_env_var_for(agent_conf: dict) -> str:
    """model_env_var from the config entry, else from the manifest on disk
    (entries created before v0.1.0 didn't record it)."""
    declared = agent_conf.get("model_env_var", "")
    if declared:
        return declared
    src = agent_conf.get("source_path", "")
    if src:
        try:
            with open(os.path.join(src, "costaff.agent.json")) as f:
                return json.load(f).get("model_env_var", "") or ""
        except (OSError, ValueError):
            return ""
    return ""


def _external_target(agent_name: str, agent_conf: dict) -> dict:
    """Build the write-target descriptor for an external agent."""
    return {
        "name": agent_name,
        "model_env_var": _model_env_var_for(agent_conf),
        "provider_env_var": agent_conf.get(
            "provider_env_var",
            "COSTAFF_AGENT_MODEL_PROVIDER" if _model_env_var_for(agent_conf) else "",
        ),
        "env_path": _plugin_env_path(agent_conf),
    }


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
    core_name: Optional[str] = CORE_OPT,
):
    """Set or view model configuration for an agent."""
    core = _resolve_core(core_name)
    env_path = core.env_path
    conf = core.core_config()
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
            t = _external_target(agent_name, agent_conf)
            # Effective value = plugin .env (wins in env_file order) → core .env
            def _eff(var: str) -> str:
                if not var:
                    return ""
                return (
                    (_read_env_key(t["env_path"], var) if t["env_path"] else "")
                    or _read_env_key(env_path, var)
                )
            p_val = _eff(t["provider_env_var"]) or global_provider
            m_val = _eff(t["model_env_var"]) or "gemini-3-flash-preview"
            api = _read_env_key(env_path, "LITELLM_API_BASE") if p_val == "litellm" else "—"
            table.add_row(agent_name, p_val, m_val, api or "—")

        console.print(table)
        return

    # Determine which agent(s) to configure. Each target carries its OWN
    # env_path — core .env for the core agent, plugin .env for externals.
    targets: list[dict] = []

    if name is None:
        # Global: apply to all
        targets.append({**_CORE_AGENT, "env_path": env_path})
        for agent_name, agent_conf in agents.items():
            targets.append(_external_target(agent_name, agent_conf))
    elif name == "costaff-agent-costaff":
        targets.append({**_CORE_AGENT, "env_path": env_path})
    else:
        if name not in agents:
            console.print(f"[red]Error: Agent '{name}' not found. Use 'costaff agent list' to see available agents.[/red]")
            raise typer.Exit(1)
        targets.append(_external_target(name, agents[name]))

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

    # Write env vars — each target into its OWN env file. Success is only
    # claimed for agents that were actually written; a target with no model
    # surface (url-type remote agent, or a plugin without model_env_var) is
    # reported instead of silently "succeeding".
    configured: list[str] = []
    skipped: list[str] = []
    for t in targets:
        target_env = t.get("env_path", "")
        writable = target_env and (t.get("model_env_var") or t.get("provider_env_var"))
        if not writable:
            skipped.append(t["name"])
            continue
        if t.get("provider_env_var"):
            _write_env_key(target_env, t["provider_env_var"], final_provider)
        if t.get("model_env_var") and final_model:
            _write_env_key(target_env, t["model_env_var"], final_model)
        if final_provider == "litellm":
            # LiteLLM connection settings are read inside the agent's own
            # containers, so they go to the same per-target env file.
            if api_base:
                _write_env_key(target_env, "LITELLM_API_BASE", api_base)
            if api_key:
                _write_env_key(target_env, "LITELLM_API_KEY", api_key)
            if final_model:
                _write_env_key(target_env, "LITELLM_MODEL_NAME", final_model)
        configured.append(t["name"])

    for s in skipped:
        console.print(
            f"[yellow]Skipped '{s}': no model configuration surface — the "
            f"agent is managed remotely (url type) or its entry/manifest "
            f"declares no model_env_var.[/yellow]"
        )
    if not configured:
        console.print("[red]No agent was updated.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Model updated for {', '.join(configured)}: "
        f"provider=[bold]{final_provider}[/bold], model=[bold]{final_model}[/bold][/green]"
    )
    if configured == ["costaff-agent-costaff"]:
        console.print("[yellow]Run 'costaff restart' to apply (env_file is only read at container creation).[/yellow]")
    else:
        console.print(
            "[yellow]Run 'costaff agent rebuild <name> --no-pull' on each updated agent "
            "to apply (env_file is only read at container creation; plain restart is not enough).[/yellow]"
        )
