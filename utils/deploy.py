"""Local deployment of agent / channel plugins from a source path.

These functions are invoked by the CLI's `agent add --local` and
`channel add --local` commands. They:
  1. Read the plugin manifest (`costaff.agent.json` / `costaff.channel.json`)
  2. Allocate a public port via `utils.ports`
  3. Prompt the user for env vars via `utils.plugin_env`
  4. Generate a compose-fragment.yaml via `utils.compose` (channels)
     or directly here (agents — Plan B private + shared workspaces)
  5. Run `docker compose up -d --build --force-recreate`
  6. Health-check the result and return a config dict for `config.json`
"""
import json
import os
import time

from .paths import PATHS, _base_dir, _runtime_root, _project_root, _workspace_root
from .ports import _next_available_port, _next_available_channel_port
from .plugin_env import _prompt_and_write_plugin_env
from .compose import _write_channel_fragment


def _deploy_local_channel(name: str, source_path: str, conf: dict, predefined_envs: dict = None, build_only: bool = False) -> dict:
    """Build (and optionally start) a local-path communication channel following CoStaff Convention."""
    from dotenv import load_dotenv
    from services.docker import DockerManager

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
    fragment_dir = os.path.join(_base_dir, "costaff-channel", name)
    os.makedirs(fragment_dir, exist_ok=True)

    plugin_env_path = _prompt_and_write_plugin_env(manifest, fragment_dir, predefined_envs, name=name)
    load_dotenv(PATHS["env"], override=True)

    fragment_path, ext_services, _ = _write_channel_fragment(name, source_path, public_port, plugin_env_path)

    # Sync MCP_SERVER_URLS before container creation so the agent container
    # is created with the bearer-form URL instead of the anonymous default
    # from .env.template. Without this, scenarios that skip `costaff onboard`
    # (e.g. manual .env setup) end up with the manager agent hitting MCP
    # with no auth header → 401 Unauthorized.
    from services.config import ConfigManager
    ConfigManager.update_mcp_urls()
    load_dotenv(PATHS["env"], override=True)

    from rich.console import Console
    console = Console()
    main_compose = os.path.join(_runtime_root, "docker-compose.yaml")
    import subprocess
    if build_only:
        cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "build"] + ext_services
        console.print(f"Building channel {name}...")
    else:
        cmd = DockerManager.get_cmd() + ["-f", main_compose, "-f", fragment_path, "up", "-d", "--build", "--force-recreate"]
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


def _deploy_local_agent(
    name: str,
    source_path: str,
    conf: dict,
    predefined_envs: dict = None,
    strict: bool = False,
    core=None,
) -> dict:
    """Build and start a local-path agent following CoStaff Agent Convention.

    `strict=True` runs full JSON Schema validation against the bundled
    Agent Protocol schema; otherwise only protocol-version compatibility
    is enforced (legacy manifests without protocol_version warn instead
    of fail). See services.agent_protocol for details.

    `core` (services.cores.CoreContext) targets the deploy at a specific
    core's paths / container prefix / compose project. None → the active
    core, which on single-install hosts is the synthetic default with the
    exact historical layout.
    """
    import yaml as _yaml
    from dotenv import load_dotenv
    from services.docker import DockerManager
    from services.agent_protocol import ProtocolError, validate_manifest
    from services.cores import active_core, all_used_public_ports

    if core is None:
        core = active_core()

    source_path = os.path.abspath(source_path)
    manifest_path = os.path.join(source_path, "costaff.agent.json")
    compose_path = os.path.join(source_path, "docker-compose.yaml")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"costaff.agent.json not found in {source_path}")
    if not os.path.exists(compose_path):
        raise FileNotFoundError(f"docker-compose.yaml not found in {source_path}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Validate against the CoStaff Agent Protocol before doing any work.
    try:
        warnings = validate_manifest(manifest, strict=strict)
    except ProtocolError as e:
        raise ValueError(f"costaff.agent.json fails Agent Protocol: {e}") from e
    for w in warnings:
        print(f"[warn] {w}")

    a2a_service = manifest.get("a2a_service", name)
    port = manifest.get("port", 8081)
    description = manifest.get("description", "")
    version = manifest.get("version", "")

    public_port = _next_available_port(conf, reserved=all_used_public_ports())
    fragment_dir = os.path.join(core.base_dir, "costaff-agent", name)
    os.makedirs(fragment_dir, exist_ok=True)

    plugin_env_path = _prompt_and_write_plugin_env(
        manifest, fragment_dir, predefined_envs, name=name,
        core_env_path=core.env_path, container_prefix=core.prefix,
    )
    load_dotenv(core.env_path, override=True)

    # Plan B workspace directories: private per-agent + shared
    agent_container_name = f"{core.prefix}-agent-{name}"
    private_host_dir = os.path.join(core.workspace_root, agent_container_name)
    shared_host_dir = os.path.join(core.workspace_root, "shared")
    agent_shared_host_dir = os.path.join(shared_host_dir, agent_container_name)
    os.makedirs(private_host_dir, exist_ok=True)
    os.makedirs(agent_shared_host_dir, exist_ok=True)

    # Env vars inside container (Plan B naming convention)
    NAME_UPPER = name.upper().replace("-", "_")
    AGENT_WORKSPACE_ENV_KEY = f"AGENT_WORKSPACE_DIR_{NAME_UPPER}"
    COSTAFF_SHARED_ENV_KEY = f"COSTAFF_SHARED_DIR_{NAME_UPPER}"
    CONTAINER_WORKSPACE = "/app/data"
    CONTAINER_SHARED = "/app/data/shared"
    CONTAINER_MY_SHARED = f"/app/data/shared/{agent_container_name}"

    # Read source compose
    with open(compose_path) as f:
        src_compose = _yaml.safe_load(f)
    service_names = list(src_compose.get("services", {}).keys())

    def _svc_to_container(svc, svc_def):
        explicit = svc_def.get("container_name")
        if explicit:
            return explicit
        return f"{core.prefix}-{svc}"

    a2a_container_name_val = _svc_to_container(a2a_service, src_compose["services"].get(a2a_service, {}))

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
        # Rename depends_on references
        if "depends_on" in svc_def:
            old_deps = svc_def["depends_on"]
            if isinstance(old_deps, list):
                svc_def["depends_on"] = [
                    _svc_to_container(d, src_compose["services"].get(d, {}))
                    for d in old_deps
                ]
        svc_def["container_name"] = ext_svc
        services_fragment[ext_svc] = svc_def

    # Inject Plan B env vars and volumes into all services
    skip_env_keys = {"WORKSPACE_DIR", "DATA_DIR", "SHARED_DIR", AGENT_WORKSPACE_ENV_KEY, COSTAFF_SHARED_ENV_KEY}
    for svc_name, svc_def in services_fragment.items():
        svc_def.setdefault("environment", [])
        # Strip old workspace-related vars that we'll replace
        updated_envs = [
            e for e in svc_def["environment"]
            if not ("=" in e and (
                e.split("=", 1)[0] in skip_env_keys
                or e.split("=", 1)[0].endswith("_WORKSPACE_DIR")
                or e.split("=", 1)[0].startswith("COSTAFF_SHARED_DIR_")
            ))
        ]
        updated_envs += [
            f"WORKSPACE_DIR={CONTAINER_WORKSPACE}",
            f"SHARED_DIR={CONTAINER_SHARED}",
            f"{COSTAFF_SHARED_ENV_KEY}={CONTAINER_MY_SHARED}",
            f"{AGENT_WORKSPACE_ENV_KEY}={CONTAINER_WORKSPACE}",
        ]
        svc_def["environment"] = updated_envs

        # Plan B volumes: private bind mount + shared bind mount
        new_vols = [
            f"{private_host_dir}:{CONTAINER_WORKSPACE}",
            f"{shared_host_dir}:{CONTAINER_SHARED}",
        ]
        for vol in svc_def.get("volumes", []):
            if ":" in str(vol):
                _, container_part = str(vol).split(":", 1)
                if container_part.startswith("/app/data"):
                    continue
            new_vols.append(vol)
        svc_def["volumes"] = new_vols

    # Inject env_file into all services
    for svc_def in services_fragment.values():
        svc_def["env_file"] = [core.env_path, plugin_env_path]

    fragment = {
        "services": services_fragment,
        "networks": {"costaff_default": {"external": True}},
    }
    fragment_path = os.path.join(fragment_dir, "compose-fragment.yaml")
    if os.path.exists(fragment_path):
        os.remove(fragment_path)

    with open(fragment_path, "w") as f:
        _yaml.dump(fragment, f, default_flow_style=False, allow_unicode=True)

    # Sync MCP_SERVER_URLS before container creation — see _deploy_local_channel
    # for the rationale (manual-onboard installs otherwise hit MCP with no auth).
    core.regen_mcp_urls()
    load_dotenv(core.env_path, override=True)

    # Build & start (scoped to this core's compose project so containers land
    # on the right stack and don't name-conflict across cores)
    import httpx
    from rich.console import Console
    console = Console()
    ext_services = list(services_fragment.keys())
    cmd = DockerManager.get_cmd()
    if core.compose_project:
        cmd += ["-p", core.compose_project]
    cmd += ["-f", core.main_compose, "-f", fragment_path, "up", "-d", "--build", "--force-recreate"]
    cmd += ext_services
    console.print(f"Building and starting {name} (core: {core.name})...")
    import subprocess
    compose_cwd = core.runtime_root if os.path.isdir(core.runtime_root) else _project_root
    result = subprocess.run(cmd, cwd=compose_cwd)
    if result.returncode != 0:
        raise RuntimeError("docker compose up failed")

    # Health check (30s)
    health_url = f"http://localhost:{public_port}/.well-known/agent-card.json"
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

    result_dict = {
        "type": "github",
        "source_path": source_path,
        "fragment_path": fragment_path,
        "a2a_url": f"http://{a2a_container_name_val}:{port}",
        "public_port": public_port,
        "description": description,
        "version": version,
        "enabled": True,
        "container_names": ext_services,
    }
    if manifest.get("mcp_configurable"):
        result_dict["mcp_configurable"] = True
        result_dict["mcp_env_var"] = manifest.get("mcp_env_var", name.replace("-", "_").upper() + "_MCP_URLS")
    return result_dict
