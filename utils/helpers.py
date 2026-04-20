import os
import sys
import json
import time
import questionary
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dotenv import set_key

# _project_root  — source code directory (git clone at ~/.costaff)
# _runtime_root  — runtime data directory (~/.costaff, same as _project_root)
#   Override _runtime_root via COSTAFF_HOME env var.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_runtime_root: str = os.environ.get("COSTAFF_HOME") or str(Path.home() / ".costaff")

# --- Constants ---
VERSION = "0.2.4"
PATHS = {
    "env":      os.path.join(_runtime_root, ".env"),
    "config":   os.path.join(_runtime_root, "config.json"),
    "auth":     os.path.join(_runtime_root, "auth.json"),
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


def _validate_cron(cron: str) -> None:
    """Raises ValueError if the cron expression is not a valid 5-field format."""
    import re
    pattern = re.compile(
        r'^(\*|[0-9*/,\-]+)\s+'   # minute
        r'(\*|[0-9*/,\-]+)\s+'   # hour
        r'(\*|[0-9?*/,\-L]+)\s+' # day-of-month
        r'(\*|[0-9*/,\-]+)\s+'   # month
        r'(\*|[0-9?*/,\-L]+)$'   # day-of-week
    )
    if not pattern.match(cron.strip()):
        raise ValueError(
            f"Invalid cron expression: '{cron}'. "
            "Expected 5 fields: minute hour day-of-month month day-of-week"
        )


def _validate_a2a_url(url: str) -> None:
    """Raises ValueError if the URL is not a safe external http/https endpoint."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("Invalid URL format")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    hostname = (parsed.hostname or "").lower()
    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", ""}
    if hostname in blocked:
        raise ValueError(f"URL hostname '{hostname}' is not allowed")


def _next_available_port(conf: dict) -> int:
    used = {a.get("public_port") for a in conf.get("external_agents", {}).values() if a.get("public_port")}
    for p in range(18100, 18200):
        if p not in used:
            return p
    raise RuntimeError("No available ports in range 18100-18199")


def _next_available_channel_port(conf: dict) -> int:
    used = {c.get("public_port") for c in conf.get("dynamic_channels", {}).values() if c.get("public_port")}
    for p in range(18090, 18100):
        if p not in used:
            return p
    raise RuntimeError("No available ports in range 18090-18099")


DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


def _prompt_model_config(manifest: dict, plugin_envs: dict, core_envs: dict) -> dict:
    """Prompt user to select model provider and model for this agent. Returns updated plugin_envs."""
    model_env_var = manifest.get("model_env_var")
    if not model_env_var:
        return plugin_envs

    current_provider = plugin_envs.get("COSTAFF_AGENT_MODEL_PROVIDER") or core_envs.get("COSTAFF_AGENT_MODEL_PROVIDER", "gemini")
    current_model = plugin_envs.get(model_env_var) or core_envs.get(model_env_var, "")

    provider = questionary.select(
        f"Model provider for {manifest.get('name', 'this agent')}:",
        choices=["gemini", "litellm"],
        default=current_provider,
    ).ask()
    if not provider:
        return plugin_envs

    plugin_envs["COSTAFF_AGENT_MODEL_PROVIDER"] = provider

    if provider == "gemini":
        model = questionary.text(
            "Gemini model name:",
            default=current_model or DEFAULT_GEMINI_MODEL,
        ).ask()
        if model:
            plugin_envs[model_env_var] = model

    elif provider == "litellm":
        model = questionary.text(
            "LiteLLM model name (e.g. openai/gpt-4o):",
            default=current_model or "",
        ).ask()
        api_base = questionary.text(
            "LiteLLM API base URL:",
            default=plugin_envs.get("LITELLM_API_BASE") or core_envs.get("LITELLM_API_BASE", ""),
        ).ask()
        api_key = questionary.password("LiteLLM API key:").ask()
        if model:
            plugin_envs[model_env_var] = model
            plugin_envs["LITELLM_MODEL_NAME"] = model
        if api_base:
            plugin_envs["LITELLM_API_BASE"] = api_base
        if api_key:
            plugin_envs["LITELLM_API_KEY"] = api_key

    return plugin_envs


def _prompt_and_write_plugin_env(manifest: dict, fragment_dir: str, predefined_envs: dict = None) -> str:
    """Prompt user for env vars defined in manifest and write to plugin .env. Returns plugin env path."""
    from dotenv import dotenv_values, set_key
    plugin_env_path = os.path.join(fragment_dir, ".env")
    core_envs = dict(dotenv_values(PATHS["env"]))
    plugin_envs = dict(dotenv_values(plugin_env_path)) if os.path.exists(plugin_env_path) else {}

    if predefined_envs:
        plugin_envs.update(predefined_envs)

    env_required = manifest.get("env_required", [])
    env_optional = manifest.get("env_optional", [])

    # Required vars — always prompt if missing
    for k in env_required:
        current = plugin_envs.get(k) or core_envs.get(k, "")
        if not current:
            val = questionary.password(f"[Required] {k}:").ask()
            if not val:
                raise ValueError(f"Required env var {k} not provided")
            plugin_envs[k] = val
        elif sys.stdin.isatty() and (not predefined_envs or k not in predefined_envs):
            update = questionary.confirm(f"[Required] {k} is already set. Update?", default=False).ask()
            if update:
                val = questionary.password(f"{k}:", default="").ask()
                if val:
                    plugin_envs[k] = val

    # Model config — only for agents (manifest has model_env_var)
    if manifest.get("model_env_var") and sys.stdin.isatty():
        plugin_envs = _prompt_model_config(manifest, plugin_envs, core_envs)

    # Optional vars — ask if user wants to configure
    if env_optional and sys.stdin.isatty():
        configure_optional = questionary.confirm("Configure optional variables?", default=False).ask()
        if configure_optional:
            for k in env_optional:
                current = plugin_envs.get(k) or core_envs.get(k, "")
                val = questionary.text(f"[Optional] {k}:", default=current).ask()
                if val is not None:
                    plugin_envs[k] = val

    # Write plugin .env
    os.makedirs(fragment_dir, exist_ok=True)
    with open(plugin_env_path, "w") as f:
        for k, v in plugin_envs.items():
            f.write(f"{k}={v}\n")

    # Also write required vars to core .env for YAML variable substitution
    for k in env_required:
        if plugin_envs.get(k):
            set_key(PATHS["env"], k, plugin_envs[k])

    return plugin_env_path


def _write_channel_fragment(name: str, source_path: str, public_port: int, plugin_env_path: str) -> tuple[str, list, dict]:
    """Generate compose-fragment.yaml from the source docker-compose.yaml. Returns (fragment_path, ext_services, manifest)."""
    import yaml as _yaml

    manifest_path = os.path.join(source_path, "costaff.channel.json")
    if not os.path.exists(manifest_path):
        manifest_path = os.path.join(source_path, "costaff.agent.json")
    compose_path = os.path.join(source_path, "docker-compose.yaml")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found in {source_path}")
    if not os.path.exists(compose_path):
        raise FileNotFoundError(f"docker-compose.yaml not found in {source_path}")

    with open(manifest_path) as f:
        manifest = json.load(f)
    a2a_service = manifest.get("a2a_service", name)
    port = manifest.get("port", 80)

    with open(compose_path) as f:
        src_compose = _yaml.safe_load(f)

    SHARED_VOLUME = "costaff_data"
    services_fragment = {}
    for svc, svc_def in src_compose.get("services", {}).items():
        ext_svc = f"costaff-channel-{name}-{svc}" if svc != a2a_service else f"costaff-channel-{name}"
        svc_def = svc_def.copy()
        # Force the container_name to match the service key so downstream tooling
        # (doctor, rebuild, logs) can find containers by the names stored in config.json,
        # regardless of what the source repo's docker-compose.yaml specifies.
        svc_def["container_name"] = ext_svc
        if "build" in svc_def:
            build = svc_def["build"]
            if isinstance(build, str):
                svc_def["build"] = os.path.join(source_path, build)
            elif isinstance(build, dict) and "context" in build:
                svc_def["build"]["context"] = os.path.join(source_path, build["context"])

        svc_def.pop("ports", None)
        svc_def.setdefault("networks", [])
        if "costaff_default" not in svc_def["networks"]:
            svc_def["networks"].append("costaff_default")

        if svc == a2a_service:
            svc_def.setdefault("environment", [])
            svc_def["environment"] += [f"PORT={port}"]
            svc_def["ports"] = [f"0.0.0.0:{public_port}:{port}"]

        new_vols = []
        for vol in svc_def.get("volumes", []):
            if ":" in str(vol):
                local_part, container_part = vol.split(":", 1)
                if not local_part.startswith("/") and not local_part.startswith("./"):
                    if container_part.startswith("/app/data"):
                        new_vols.append(f"{SHARED_VOLUME}:{container_part}")
                        continue
            new_vols.append(vol)
        svc_def["volumes"] = new_vols
        svc_def["env_file"] = [PATHS["env"], plugin_env_path]
        services_fragment[ext_svc] = svc_def

    fragment = {
        "services": services_fragment,
        "networks": {"costaff_default": {"external": True}},
        "volumes": {SHARED_VOLUME: {"external": True}},
    }
    fragment_dir = os.path.dirname(plugin_env_path)
    fragment_path = os.path.join(fragment_dir, "compose-fragment.yaml")
    with open(fragment_path, "w") as f:
        _yaml.dump(fragment, f, default_flow_style=False, allow_unicode=True)

    return fragment_path, list(services_fragment.keys()), manifest


def _deploy_local_channel(name: str, source_path: str, conf: dict, predefined_envs: dict = None, build_only: bool = False) -> dict:
    """Build (and optionally start) a local-path communication channel following CoStaff Convention."""
    from dotenv import load_dotenv
    from managers.docker import DockerManager

    source_path = os.path.abspath(source_path)
    manifest_path = os.path.join(source_path, "costaff.channel.json")
    if not os.path.exists(manifest_path):
        manifest_path = os.path.join(source_path, "costaff.agent.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found in {source_path}")

    with open(manifest_path) as f:
        manifest = json.load(f)
    description = manifest.get("description", "")

    public_port = _next_available_channel_port(conf)
    fragment_dir = os.path.join(_runtime_root, "dynamic-channels", name)
    os.makedirs(fragment_dir, exist_ok=True)

    plugin_env_path = _prompt_and_write_plugin_env(manifest, fragment_dir, predefined_envs)
    load_dotenv(PATHS["env"], override=True)

    fragment_path, ext_services, _ = _write_channel_fragment(name, source_path, public_port, plugin_env_path)

    from rich.console import Console
    console = Console()
    main_compose = os.path.join(_runtime_root, "docker-compose.yaml")
    import subprocess
    if build_only:
        cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "build"] + ext_services
        console.print(f"Building channel {name}...")
    else:
        cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d", "--build"] + ext_services
        console.print(f"Building and starting channel {name}...")
    subprocess.run(cmd, cwd=_project_root)

    return {
        "type": "github",
        "source_path": source_path,
        "fragment_path": fragment_path,
        "public_port": public_port,
        "description": description,
        "enabled": True,
        "container_names": ext_services,
    }


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

    public_port = _next_available_port(conf)
    fragment_dir = os.path.join(_runtime_root, "external-agents", name)
    os.makedirs(fragment_dir, exist_ok=True)

    plugin_env_path = _prompt_and_write_plugin_env(manifest, fragment_dir, predefined_envs)
    load_dotenv(PATHS["env"], override=True)

    # Read source compose to get all service names
    with open(compose_path) as f:
        src_compose = _yaml.safe_load(f)
    service_names = list(src_compose.get("services", {}).keys())

    # Generate compose fragment — use container_name from repo if defined, else derive from service key
    def _svc_to_container(svc, svc_def):
        explicit = svc_def.get("container_name")
        if explicit:
            return explicit
        return f"costaff-{svc}" if svc.startswith("costaff-") else f"costaff-{svc}"

    a2a_container_name = _svc_to_container(a2a_service, src_compose["services"].get(a2a_service, {}))

    services_fragment = {}
    for svc in service_names:
        src_def = src_compose["services"][svc]
        ext_svc = _svc_to_container(svc, src_def)
        svc_def = src_def.copy()
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
        # Inject fixed runtime vars into a2a service
        if svc == a2a_service:
            svc_def.setdefault("environment", [])
            svc_def["environment"] += [f"PORT={port}", f"PUBLIC_HOST={ext_svc}"]
            svc_def["ports"] = [f"127.0.0.1:{public_port}:{port}"]
        # Rename depends_on references to use resolved container names
        if "depends_on" in svc_def:
            old_deps = svc_def["depends_on"]
            if isinstance(old_deps, list):
                svc_def["depends_on"] = [
                    _svc_to_container(d, src_compose["services"].get(d, {}))
                    for d in old_deps
                ]
        # Force container_name to match the resolved name
        svc_def["container_name"] = ext_svc
        services_fragment[ext_svc] = svc_def

    # Volumes: map agent-specific data volumes to the global costaff_data volume
    SHARED_VOLUME = "costaff_data"
    
    for svc_name, svc_def in services_fragment.items():
        new_vols = []
        has_shared_mount = False
        
        for vol in svc_def.get("volumes", []):
            if ":" in str(vol):
                local_part, container_part = vol.split(":", 1)
                # If any volume maps to /app/data, redirect it to SHARED_VOLUME
                if container_part.startswith("/app/data"):
                    new_vols.append(f"{SHARED_VOLUME}:{container_part}")
                    has_shared_mount = True
                    continue
            new_vols.append(vol)
        
        # [NEW] Proactive injection: If no shared workspace is defined, add it.
        # This ensures even "lazy" agents can see the shared data.
        if not has_shared_mount:
            new_vols.append(f"{SHARED_VOLUME}:/app/data")
            
        svc_def["volumes"] = new_vols

    # Inject env_file into all services
    core_env_path = PATHS["env"]
    for svc_def in services_fragment.values():
        svc_def["env_file"] = [core_env_path, plugin_env_path]

    fragment = {
        "services": services_fragment,
        "networks": {"costaff_default": {"external": True}},
        "volumes": {SHARED_VOLUME: {"external": True}},
    }
    fragment_path = os.path.join(fragment_dir, "compose-fragment.yaml")
    with open(fragment_path, "w") as f:
        _yaml.dump(fragment, f, default_flow_style=False, allow_unicode=True)

    # Build & start
    import httpx
    from rich.console import Console
    console = Console()
    main_compose = os.path.join(_runtime_root, "docker-compose.yaml")
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
        "a2a_url": f"http://{a2a_container_name}:{port}",
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
