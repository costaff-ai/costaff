import subprocess

import typer
from rich.console import Console

from managers.config import ConfigManager
from managers.docker import DockerManager
from utils.helpers import PATHS

console = Console()


def start(build: bool = typer.Option(True, "--build/--no-build")):
    """Start CoStaff services."""
    conf = ConfigManager.get_config()
    services = ["costaff-agent", "postgres"]
    for p in conf.get("channels", []):
        services.append(f"bot-{'telegram' if p=='tg' else 'discord' if p=='dc' else 'line'}")
    for m in conf.get("mcp", []):
        services.append(f"mcp-{m}")

    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    cmd = DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "up", "-d"]
    if build:
        cmd.append("--build")
    cmd.extend(services)

    console.print("Starting CoStaff...")
    subprocess.run(cmd, check=True, cwd=compose_cwd)

    # Start dynamic channels (each has its own compose fragment)
    for name, entry in conf.get("dynamic_channels", {}).items():
        if not entry.get("enabled"):
            continue
        fragment_path = entry.get("fragment_path")
        container_names = entry.get("container_names", [])
        if not fragment_path or not container_names:
            continue
        main_compose = str(__import__("pathlib").Path(compose_cwd) / "docker-compose.yaml")
        ch_cmd = DockerManager.get_cmd() + [
            "-f", main_compose, "-f", fragment_path,
            "up", "-d",
        ] + container_names
        console.print(f"Starting channel {name}...")
        subprocess.run(ch_cmd, cwd=compose_cwd)

    console.print("[bold green]SUCCESS: CoStaff started![/bold green]")


def stop():
    """Stop all services."""
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    subprocess.run(DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "down"], check=True, cwd=compose_cwd)
    # Kill any dashboard process holding port 8501
    try:
        result = subprocess.run(["lsof", "-ti", ":8501"], capture_output=True, text=True)
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                subprocess.run(["kill", pid], capture_output=True)
    except Exception:
        pass


def status():
    """Check services status."""
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    subprocess.run(DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "ps"], check=True, cwd=compose_cwd)


def logs(service: str = typer.Argument(None)):
    """Show services logs."""
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    cmd = DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "logs", "--tail", "100"]
    if service:
        cmd.append(service)
    subprocess.run(cmd, check=True, cwd=compose_cwd)
