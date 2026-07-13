"""Compose fragment generator for dynamic channels.

Reads the channel/agent source's `docker-compose.yaml` and rewrites it into a
compose-fragment.yaml that:
  - Renames each service container so the CLI can manage it by name
  - Joins the core's docker network (default core → `costaff_default`)
  - Strips the source's published ports and assigns one from our channel range
  - Adds a `SHARED_DIR` env var and bind-mounts the shared workspace dir
  - Wires both the core .env and the plugin .env as env_files
"""
import json
import os

from .paths import PATHS, _workspace_root


def _write_channel_fragment(name: str, source_path: str, public_port: int, plugin_env_path: str, core=None) -> tuple[str, list, dict]:
    """Generate compose-fragment.yaml from the source docker-compose.yaml. Returns (fragment_path, ext_services, manifest).

    `core` (services.cores.CoreContext) targets a specific core's workspace,
    container prefix, and env file. None → the historical single-install
    layout (prefix "costaff", global workspace + .env), so existing callers
    are unaffected.
    """
    import yaml as _yaml

    prefix = core.prefix if core else "costaff"
    workspace_root = core.workspace_root if core else _workspace_root
    env_path = core.env_path if core else PATHS["env"]
    net = core.network_name if core else "costaff_default"

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

    # Plan B: channels get shared bind mount only (read agent results, accept uploads)
    shared_host_dir = os.path.join(workspace_root, "shared")
    os.makedirs(shared_host_dir, exist_ok=True)
    CONTAINER_SHARED = "/app/data/shared"

    services_fragment = {}
    for svc, svc_def in src_compose.get("services", {}).items():
        ext_svc = f"{prefix}-channel-{name}-{svc}" if svc != a2a_service else f"{prefix}-channel-{name}"
        svc_def = svc_def.copy()
        # Force container_name so downstream tooling can find containers by names in config.json
        svc_def["container_name"] = ext_svc
        if "build" in svc_def:
            build = svc_def["build"]
            if isinstance(build, str):
                svc_def["build"] = os.path.join(source_path, build)
            elif isinstance(build, dict) and "context" in build:
                svc_def["build"]["context"] = os.path.join(source_path, build["context"])

        svc_def.pop("ports", None)
        svc_def.setdefault("networks", [])
        if net not in svc_def["networks"]:
            svc_def["networks"].append(net)

        if svc == a2a_service:
            svc_def.setdefault("environment", [])
            svc_def["environment"] += [f"PORT={port}"]
            # Localhost by default (same as agent fragments in utils/deploy).
            # A channel that must accept traffic from other machines directly
            # (no tunnel / reverse proxy) opts in with
            # COSTAFF_CHANNEL_BIND=0.0.0.0 at `channel add` time; the value
            # is baked into the fragment. Existing fragments are untouched.
            bind = os.getenv("COSTAFF_CHANNEL_BIND", "127.0.0.1")
            svc_def["ports"] = [f"{bind}:{public_port}:{port}"]

        # Inject SHARED_DIR env var
        env_list = svc_def.get("environment", [])
        if not any("SHARED_DIR=" in e for e in env_list if isinstance(e, str)):
            env_list.append(f"SHARED_DIR={CONTAINER_SHARED}")
        svc_def["environment"] = env_list

        # Replace all /app/data mounts with shared bind mount
        new_vols = []
        has_shared = False
        for vol in svc_def.get("volumes", []):
            if ":" in str(vol):
                local_part, container_part = vol.split(":", 1)
                if not local_part.startswith("/") and not local_part.startswith("./"):
                    if container_part.startswith("/app/data"):
                        if not has_shared:
                            new_vols.append(f"{shared_host_dir}:{CONTAINER_SHARED}")
                            has_shared = True
                        continue
            new_vols.append(vol)
        if not has_shared:
            new_vols.append(f"{shared_host_dir}:{CONTAINER_SHARED}")
        svc_def["volumes"] = new_vols
        svc_def["env_file"] = [env_path, plugin_env_path]
        services_fragment[ext_svc] = svc_def

    fragment = {
        "services": services_fragment,
        "networks": {net: {"external": True}},
    }
    fragment_dir = os.path.dirname(plugin_env_path)
    fragment_path = os.path.join(fragment_dir, "compose-fragment.yaml")
    if os.path.exists(fragment_path):
        os.remove(fragment_path)

    with open(fragment_path, "w") as f:
        _yaml.dump(fragment, f, default_flow_style=False, allow_unicode=True)

    return fragment_path, list(services_fragment.keys()), manifest
