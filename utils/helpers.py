import os
import sys
import json
import time
import questionary
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dotenv import set_key

# Resolve project root: prefer CWD if it looks like the project (has costaff.py or setup.py),
# otherwise fall back to the directory containing this file (works for editable installs).
def _find_project_root() -> str:
    cwd = Path.cwd()
    if (cwd / "setup.py").exists() or (cwd / "costaff.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parent.parent)

_project_root = _find_project_root()
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# --- Constants ---
VERSION = "0.2.4"
PATHS = {
    "env": os.path.join(_project_root, ".costaff", ".env"),
    "config": os.path.join(_project_root, ".costaff", "config.json"),
    "auth": os.path.join(_project_root, ".costaff", "auth.json"),
    "frontend": os.path.join(_project_root, "frontend"),
}


def _dt_to_z(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(v)


def _serialize_row(d: dict) -> dict:
    return {k: _dt_to_z(v) if isinstance(v, datetime) else v for k, v in d.items()}


def _next_available_port(conf: dict) -> int:
    used = {a.get("public_port") for a in conf.get("external_agents", {}).values() if a.get("public_port")}
    for p in range(18100, 18200):
        if p not in used:
            return p
    raise RuntimeError("No available ports in range 18100-18199")


def _deploy_local_agent(name: str, source_path: str, conf: dict, predefined_envs: dict = None) -> dict:
    """Build and start a local-path agent following CoStaff Agent Convention."""
    import yaml as _yaml
    from dotenv import load_dotenv
    from utils.helpers import PATHS, _project_root, _next_available_port
    from managers.docker import DockerManager

    source_path = os.path.abspath(source_path)
    manifest_path = os.path.join(source_path, "costaff.agent.json")
    compose_path = os.path.join(source_path, "docker-compose.yaml")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"costaff.agent.json not found in {source_path}")
    if not os.path.exists(compose_path):
        raise FileNotFoundError(f"docker-compose.yaml not found in {source_path}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    a2a_service = manifest.get("a2a_service", name)
    port = manifest.get("port", 8081)
    description = manifest.get("description", "")
    version = manifest.get("version", "")

    # Handle predefined envs first
    if predefined_envs:
        for k, v in predefined_envs.items():
            set_key(PATHS["env"], k, v)
        load_dotenv(PATHS["env"], override=True)

    # Check env_required
    load_dotenv(PATHS["env"])
    missing = [k for k in manifest.get("env_required", []) if not os.getenv(k)]
    if missing:
        for k in missing:
            val = questionary.password(f"Required env var {k}:").ask()
            if not val:
                raise ValueError(f"Required env var {k} not provided")
            set_key(PATHS["env"], k, val)
        load_dotenv(PATHS["env"], override=True)

    public_port = _next_available_port(conf)
    fragment_dir = os.path.join(_project_root, ".costaff", "external-agents", name)
    os.makedirs(fragment_dir, exist_ok=True)

    # Read source compose to get all service names
    with open(compose_path) as f:
        src_compose = _yaml.safe_load(f)
    service_names = list(src_compose.get("services", {}).keys())

    # Build env injection from env_required + env_optional
    env_vars = []
    for k in manifest.get("env_required", []) + manifest.get("env_optional", []):
        v = os.getenv(k, "")
        env_vars.append(f"      - {k}={v}")

    # Generate compose fragment
    services_fragment = {}
    for svc in service_names:
        ext_svc = f"costaff-ext-{name}-{svc}" if svc != a2a_service else f"costaff-ext-{name}"
        svc_def = src_compose["services"][svc].copy()
        # Rewrite build context to absolute path
        if "build" in svc_def:
            build = svc_def["build"]
            if isinstance(build, str):
                svc_def["build"] = os.path.join(source_path, build)
            elif isinstance(build, dict) and "context" in build:
                svc_def["build"]["context"] = os.path.join(source_path, build["context"])
        # Remove original ports (we manage them)
        svc_def.pop("ports", None)
        # Add to costaff network
        svc_def.setdefault("networks", [])
        if isinstance(svc_def["networks"], list) and "costaff_default" not in svc_def["networks"]:
            svc_def["networks"].append("costaff_default")
        # Inject env vars into a2a service
        if svc == a2a_service:
            svc_def.setdefault("environment", [])
            svc_def["environment"] += [f"PORT={port}", f"PUBLIC_HOST=costaff-ext-{name}"]
            for k in manifest.get("env_required", []) + manifest.get("env_optional", []):
                v = os.getenv(k, "")
                if v:
                    svc_def["environment"].append(f"{k}={v}")
            svc_def["ports"] = [f"127.0.0.1:{public_port}:{port}"]
        # Rename depends_on references
        if "depends_on" in svc_def:
            old_deps = svc_def["depends_on"]
            if isinstance(old_deps, list):
                svc_def["depends_on"] = [
                    f"costaff-ext-{name}-{d}" if d != a2a_service else f"costaff-ext-{name}"
                    for d in old_deps
                ]
        services_fragment[ext_svc] = svc_def

    # Volumes: map agent-specific data volumes to the global costaff_data volume
    volumes_fragment = {}
    for svc_name, svc_def in services_fragment.items():
        new_vols = []
        for vol in svc_def.get("volumes", []):
            if ":" in str(vol):
                local_part, container_part = vol.split(":", 1)
                # If it's a named volume (not a path) and maps to /app/data
                if not local_part.startswith("/") and not local_part.startswith("./"):
                    if container_part.startswith("/app/data"):
                        # Force use the global shared volume
                        new_vols.append(f"costaff_data:{container_part}")
                        continue
            new_vols.append(vol)
        svc_def["volumes"] = new_vols

    fragment = {
        "services": services_fragment,
        "networks": {"costaff_default": {"external": True}},
        "volumes": {"costaff_data": {"external": True}},
    }
    fragment_path = os.path.join(fragment_dir, "compose-fragment.yaml")
    with open(fragment_path, "w") as f:
        _yaml.dump(fragment, f, default_flow_style=False, allow_unicode=True)

    # Build & start
    import httpx
    from rich.console import Console
    console = Console()
    main_compose = os.path.join(_project_root, ".costaff", "docker-compose.yaml")
    ext_services = list(services_fragment.keys())
    cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d", "--build"] + ext_services
    console.print(f"Building and starting {name}...")
    import subprocess
    result = subprocess.run(cmd, cwd=_project_root)
    if result.returncode != 0:
        raise RuntimeError("docker compose up failed")

    # Health check (30s)
    health_url = f"http://localhost:{public_port}/.well-known/agent.json"
    console.print(f"Waiting for health check at {health_url}...")
    for _ in range(10):
        time.sleep(3)
        try:
            r = httpx.get(health_url, timeout=3.0)
            if r.status_code == 200:
                console.print("[green]Agent is healthy![/green]")
                break
        except Exception:
            pass
    else:
        console.print("[yellow]Warning: health check timed out. Agent may still be starting.[/yellow]")

    result = {
        "type": "github",
        "source_path": source_path,
        "fragment_path": fragment_path,
        "a2a_url": f"http://costaff-ext-{name}:{port}",
        "public_port": public_port,
        "description": description,
        "version": version,
        "enabled": True,
        "container_names": ext_services,
    }
    # Read mcp_configurable capability from manifest
    if manifest.get("mcp_configurable"):
        result["mcp_configurable"] = True
        result["mcp_env_var"] = manifest.get("mcp_env_var", name.replace("-", "_").upper() + "_MCP_URLS")
    return result
