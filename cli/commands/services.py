import subprocess
import time
import httpx

import typer
from rich.console import Console

from managers.config import ConfigManager
from managers.docker import DockerManager
from utils.helpers import PATHS

console = Console()


def _wait_for_containers(container_names: list, timeout: int = 30):
    """Wait for containers to be healthy or at least running."""
    if not container_names:
        return
    console.print(f"Waiting for {len(container_names)} services to initialize...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        all_running = True
        try:
            # Check if containers are running using docker inspect
            cmd = DockerManager.get_cmd() + ["inspect", "-f", "{{.State.Running}}"] + container_names
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                states = result.stdout.strip().split("\n")
                if all(s == "true" for s in states):
                    # Brief extra sleep to allow internal app startup
                    time.sleep(5)
                    return
            all_running = False
        except Exception:
            all_running = False
        
        if not all_running:
            time.sleep(2)
    console.print("[yellow]Warning: Some services may still be initializing.[/yellow]")


def start(build: bool = typer.Option(True, "--build/--no-build")):
    """Start CoStaff services with correct tiered sequence."""
    conf = ConfigManager.get_config()
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    main_compose = str(__import__("pathlib").Path(compose_cwd) / "docker-compose.yaml")
    
    ConfigManager.update_mcp_urls()
    
    # Tier 1: Infrastructure (Postgres)
    console.print("🚀 [bold]Step 1: Starting Infrastructure...[/bold]")
    infra_cmd = DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "up", "-d", "postgres"]
    subprocess.run(infra_cmd, check=True, cwd=compose_cwd)

    # Tier 2: External Agents & Channels (The Employees)
    employee_containers = []
    
    # External Agents
    for name, entry in conf.get("external_agents", {}).items():
        if not entry.get("enabled"): continue
        fragment_path = entry.get("fragment_path")
        container_names = entry.get("container_names", [])
        if fragment_path and container_names:
            console.print(f"🚀 [bold]Step 2: Starting Agent {name}...[/bold]")
            agent_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d"]
            if build: agent_cmd.append("--build")
            agent_cmd.extend(container_names)
            subprocess.run(agent_cmd, cwd=compose_cwd)
            employee_containers.extend(container_names)

    # Dynamic Channels
    for name, entry in conf.get("dynamic_channels", {}).items():
        if not entry.get("enabled"): continue
        fragment_path = entry.get("fragment_path")
        container_names = entry.get("container_names", [])
        if fragment_path and container_names:
            console.print(f"🚀 [bold]Step 2: Starting Channel {name}...[/bold]")
            ch_cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d"]
            if build: ch_cmd.append("--build")
            ch_cmd.extend(container_names)
            subprocess.run(ch_cmd, cwd=compose_cwd)
            employee_containers.extend(container_names)

    # Wait for Tier 2 to be ready
    if employee_containers:
        _wait_for_containers(employee_containers)

    # Tier 3: Core Agent (The Manager)
    console.print("🚀 [bold]Step 3: Starting CoStaff Manager...[/bold]")
    core_services = ["costaff-agent-costaff", "costaff-mcp-costaff"]
    core_cmd = DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "up", "-d", "--remove-orphans"]
    if build: core_cmd.append("--build")
    core_cmd.extend(core_services)
    subprocess.run(core_cmd, check=True, cwd=compose_cwd)

    console.print("[bold green]SUCCESS: CoStaff started in correct sequence![/bold green]")


def stop():
    """Stop all services."""
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    subprocess.run(DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "down", "--remove-orphans"], check=True, cwd=compose_cwd)
    # Kill any dashboard process holding port 8501
    try:
        result = subprocess.run(["lsof", "-ti", ":8501"], capture_output=True, text=True)
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                subprocess.run(["kill", pid], capture_output=True)
    except Exception:
        pass


def restart():
    """Restart CoStaff services with tiered sequence."""
    console.print("Restarting CoStaff services in sequence...")
    stop()
    start(build=False)
    console.print("[bold green]SUCCESS: CoStaff restarted in correct sequence![/bold green]")


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
