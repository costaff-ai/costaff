import os
import re
import shutil
import subprocess
import threading
from typing import Optional

import httpx
import questionary
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from managers.config import ConfigManager
from managers.docker import DockerManager
from utils.helpers import PATHS, _project_root
from utils.helpers import _deploy_local_agent

console = Console()

agent_app = typer.Typer(help="Manage external agents.")


@agent_app.command("add")
def agent_add(
    name: str = typer.Argument(..., help="Agent name (e.g. market-analyst)"),
    url: Optional[str] = typer.Option(None, "--url", help="Remote A2A endpoint URL"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path (CoStaff Agent Convention)"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL to clone and deploy"),
    env: Optional[list[str]] = typer.Option(None, "--env", "-e", help="Set environment variables (e.g. KEY=VALUE)"),
    description: str = typer.Option("", "--description", "-d", help="Short description"),
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

    # Parse provided env vars
    predefined_envs = {}
    if env:
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                predefined_envs[k.strip()] = v.strip()

    if github:
        target_src = os.path.join(_project_root, ".costaff", "src", name)
        if os.path.exists(target_src):
            if not questionary.confirm(f"Source directory {target_src} already exists. Overwrite?").ask():
                raise typer.Exit(0)
            import shutil
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
            entry = _deploy_local_agent(name, local, conf, predefined_envs=predefined_envs)
        except Exception as e:
            console.print(f"[red]Deploy failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        entry = {"type": "url", "a2a_url": url, "description": description, "enabled": True}

    conf.setdefault("external_agents", {})[name] = entry
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    threading.Thread(target=DockerManager.run_action, args=("costaff-agent", "restart"), daemon=True).start()
    console.print(f"[green]Agent '{name}' deployed and registered.[/green]")


@agent_app.command("list")
def agent_list():
    """List all external agents with health status."""
    conf = ConfigManager.get_config()
    agents = conf.get("external_agents", {})
    if not agents:
        console.print("[yellow]No external agents configured.[/yellow]")
        return
    table = Table(title="External Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="blue")
    table.add_column("A2A URL")
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    table.add_column("Description")
    for name, agent in agents.items():
        health = "—"
        if agent.get("a2a_url") and agent.get("enabled"):
            try:
                r = httpx.get(f"{agent['a2a_url']}/.well-known/agent.json", timeout=3.0)
                health = "[green]●[/green]" if r.status_code == 200 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        table.add_row(name, agent.get("type", "url"), agent.get("a2a_url", ""), health,
                      "✓" if agent.get("enabled") else "✗", (agent.get("description", "") or "")[:50])
    console.print(table)


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
    if name == "coding-agent":
        conf["coding_agent_enabled"] = False
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' removed.[/green]")
    console.print("[yellow]Restart costaff-agent to apply: costaff start[/yellow]")


@agent_app.command("enable")
def agent_enable(name: str = typer.Argument(...)):
    """Enable an external agent."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = True
    if name == "coding-agent":
        conf["coding_agent_enabled"] = True
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' enabled.[/green]")
    console.print("[yellow]Restart costaff-agent to apply changes.[/yellow]")


@agent_app.command("disable")
def agent_disable(name: str = typer.Argument(...)):
    """Disable an external agent."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    conf["external_agents"][name]["enabled"] = False
    if name == "coding-agent":
        conf["coding_agent_enabled"] = False
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    console.print(f"[green]Agent '{name}' disabled.[/green]")
    console.print("[yellow]Restart costaff-agent to apply changes.[/yellow]")


@agent_app.command("restart")
def agent_restart(name: str = typer.Argument(..., help="Agent name to restart")):
    """Restart a local agent's containers without rebuilding."""
    conf = ConfigManager.get_config()
    if name not in conf.get("external_agents", {}):
        console.print(f"[red]Error: Agent '{name}' not found.[/red]")
        raise typer.Exit(1)
    agent_conf = conf["external_agents"][name]
    if agent_conf.get("type") != "github" or not agent_conf.get("fragment_path"):
        console.print(f"[red]Error: Agent '{name}' is not a local agent (no compose fragment).[/red]")
        raise typer.Exit(1)

    fragment_path = agent_conf["fragment_path"]
    container_names = agent_conf.get("container_names", [f"costaff-ext-{name}"])
    main_compose = os.path.join(_project_root, ".costaff", "docker-compose.yaml")
    load_dotenv(PATHS["env"], override=True)

    console.print(f"Stopping agent [bold]{name}[/bold]...")
    for svc in container_names:
        subprocess.run(
            DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "stop", svc],
            check=False, cwd=_project_root,
        )

    console.print(f"Starting agent [bold]{name}[/bold]...")
    result = subprocess.run(
        DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path,
                                   "up", "-d", "--force-recreate"] + container_names,
        check=False, cwd=_project_root,
    )
    if result.returncode == 0:
        console.print(f"[green]Agent '{name}' restarted.[/green]")
    else:
        console.print(f"[red]Failed to restart agent '{name}'.[/red]")
        raise typer.Exit(1)


GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
]

# core agent env var (not in config.json external_agents)
_CORE_AGENT = {
    "name": "costaff-agent",
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
        core_model = _read_env_key(env_path, _CORE_AGENT["model_env_var"]) or "gemini-2.5-flash"
        table.add_row("costaff-agent (core)", core_provider, core_model, "—")

        for agent_name, agent_conf in agents.items():
            p_var = agent_conf.get("provider_env_var", "")
            m_var = agent_conf.get("model_env_var", "")
            p_val = (_read_env_key(env_path, p_var) if p_var else "") or global_provider
            m_val = (_read_env_key(env_path, m_var) if m_var else "") or "gemini-2.5-flash"
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
    elif name == "costaff-agent":
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
        final_model = questionary.select(
            "Select Gemini model:",
            choices=GEMINI_MODELS + ["custom (enter manually)"],
        ).ask()
        if final_model == "custom (enter manually)":
            final_model = questionary.text("Enter model name:").ask()
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

    if name and name != "costaff-agent" and agents.get(name, {}).get("type") == "github":
        console.print(f"[yellow]Run 'costaff agent restart {name}' to apply changes.[/yellow]")
    else:
        console.print("[yellow]Run 'costaff start' or restart the affected agent to apply changes.[/yellow]")


@agent_app.command("rebuild")
def agent_rebuild(
    name: str = typer.Argument(..., help="Agent name to rebuild"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
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
    container_names = agent_conf.get("container_names", [f"costaff-ext-{name}"])
    source_path = agent_conf.get("source_path", "(unknown)")
    main_compose = os.path.join(_project_root, ".costaff", "docker-compose.yaml")
    load_dotenv(PATHS["env"], override=True)

    console.print(f"Building [bold]{name}[/bold] from [cyan]{source_path}[/cyan]...")
    build_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "build"]
    if no_cache:
        build_cmd.append("--no-cache")
    build_cmd.extend(container_names)

    build_result = subprocess.run(build_cmd, cwd=_project_root)
    if build_result.returncode != 0:
        console.print(f"[red]Build failed for agent '{name}'.[/red]")
        raise typer.Exit(1)

    console.print(f"Starting rebuilt containers for [bold]{name}[/bold]...")
    up_result = subprocess.run(
        DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path,
                                   "up", "-d", "--force-recreate"] + container_names,
        cwd=_project_root,
    )
    if up_result.returncode == 0:
        console.print(f"[green]Agent '{name}' rebuilt and restarted.[/green]")
    else:
        console.print(f"[red]Failed to start agent '{name}' after build.[/red]")
        raise typer.Exit(1)
