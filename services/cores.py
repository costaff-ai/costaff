"""Multi-CoStaff core registry + active-core resolution.

The Mac Mini runs several independent CoStaff "cores" (stack / asst / twk),
each with its own container prefix, manager ADK port, postgres, and config.json.
The dashboard is host-side and can only reflect ONE core at a time; this module
makes that core switchable instead of hard-coded.

`config.json` (host install) holds the registry:

    {
      "cores": {
        "costaff": {"label": "Main",      "container_prefix": "costaff", "manager_port": 18080,
                     "db_uri": "postgresql+asyncpg://u:p@localhost:5432/costaff_db",
                     "config_path": "/Users/.../costaff-stack/costaff/config.json"},
        "asst":    {...}, "twk": {...}
      },
      "active_core": "asst"
    }

No `cores` key  →  single-core install: a synthetic "default" core that behaves
exactly as before (prefix costaff, manager 18080, DB+config from host .env/config.json).
"""
import os
import json
import re
import subprocess

from sqlalchemy import create_engine

from services.config import ConfigManager
from utils.paths import PATHS

DEFAULT_PREFIX = "costaff"


class CoreContext:
    """Resolved view of one core; all per-core lookups go through here."""

    def __init__(self, name: str, data: dict):
        self.name = name
        self.label = data.get("label") or name
        self.prefix = data.get("container_prefix") or DEFAULT_PREFIX
        self.manager_port = int(data.get("manager_port") or os.getenv("COSTAFF_AGENT_PORT", "18080"))
        self._db_uri = data.get("db_uri") or os.getenv("ADK_SESSION_SERVICE_URI", "")
        self.config_path = os.path.expanduser(data.get("config_path") or PATHS["config"])
        self.env_path = os.path.expanduser(data.get("env_path") or PATHS["env"])
        self.compose_file = data.get("compose_file") or ""
        self.compose_project = data.get("compose_project") or ""
        self.manager_service = data.get("manager_service") or self.cn("agent-costaff")

    # --- containers ---
    def cn(self, suffix: str) -> str:
        """Container name for a logical role, e.g. cn('agent-costaff')."""
        return f"{self.prefix}-{suffix}"

    @property
    def core_containers(self) -> list:
        return [self.cn("agent-costaff"), self.cn("mcp-costaff"), self.cn("postgres")]

    # --- manager ADK API ---
    def manager_url(self) -> str:
        return f"http://localhost:{self.manager_port}"

    # --- database ---
    def engine(self):
        uri = self._db_uri
        if not uri:
            return None
        uri = uri.replace("postgresql+asyncpg://", "postgresql://")
        if "postgres:5432" in uri:  # container hostname → host-reachable
            uri = uri.replace("postgres:5432", "localhost:5432")
        try:
            return create_engine(uri, pool_pre_ping=True)
        except Exception:
            return None

    # --- this core's own config.json (external_agents / channels / mcp / filters) ---
    def core_config(self) -> dict:
        try:
            with open(self.config_path) as f:
                return json.load(f)
        except Exception:
            return {}

    # --- writes (Full / per-core) ---
    def write_config(self, conf: dict):
        ConfigManager.save_config(conf, self.config_path)

    def regen_external_agents_env(self):
        ConfigManager.update_external_agents_env(self.config_path, self.env_path)

    def regen_mcp_urls(self):
        ConfigManager.update_mcp_urls(self.config_path, self.env_path, self.prefix)

    def recreate_manager(self):
        """Recreate ONLY the manager container so it reloads regenerated env.

        Uses `docker compose up -d --force-recreate --no-deps <service>` scoped to
        this core's compose project. Falls back to a plain restart for the
        synthetic single-core default (no compose metadata)."""
        import subprocess
        from services.docker import DockerManager
        if self.compose_file and self.compose_project:
            cmd = (DockerManager.get_cmd()
                   + ["-p", self.compose_project, "-f", self.compose_file,
                      "up", "-d", "--force-recreate", "--no-deps", self.manager_service])
            subprocess.run(cmd, check=False, cwd=os.path.dirname(self.compose_file))
        else:
            DockerManager.run_action(self.cn("agent-costaff"), "restart")

    def to_public(self, active: bool) -> dict:
        return {
            "name": self.name, "label": self.label, "prefix": self.prefix,
            "manager_port": self.manager_port, "active": active,
        }


def _default_core_data() -> dict:
    return {
        "label": "Default",
        "container_prefix": DEFAULT_PREFIX,
        "manager_port": int(os.getenv("COSTAFF_AGENT_PORT", "18080")),
        "db_uri": os.getenv("ADK_SESSION_SERVICE_URI", ""),
        "config_path": PATHS["config"],
    }


def _registry():
    """(cores_dict, active_name). Falls back to a single synthetic core."""
    conf = ConfigManager.get_config()
    cores = conf.get("cores")
    if not cores:
        return {"default": _default_core_data()}, "default"
    active = conf.get("active_core") or next(iter(cores))
    if active not in cores:
        active = next(iter(cores))
    return cores, active


def list_cores() -> list:
    cores, active = _registry()
    return [CoreContext(n, d).to_public(n == active) for n, d in cores.items()]


def active_core() -> CoreContext:
    cores, active = _registry()
    return CoreContext(active, cores[active])


def set_active(name: str) -> str:
    conf = ConfigManager.get_config()
    cores = conf.get("cores") or {}
    if cores and name not in cores:
        raise ValueError(f"unknown core '{name}'")
    conf["active_core"] = name
    ConfigManager.save_config(conf)
    return name


# --------------------------------------------------------------------------
# Auto-discovery: scan running `*-core` compose projects on the host.
# Run once (deploy time) to populate config.json["cores"]; the dashboard then
# just reads the registry. Requires docker + read access to each core's dir.
# --------------------------------------------------------------------------
def _host_port(ports: str, internal: str):
    """Extract published host port mapping to <internal> (e.g. '8080')."""
    m = re.search(r"0\.0\.0\.0:(\d+)->" + re.escape(internal) + r"/tcp", ports or "")
    if not m:
        m = re.search(r"127\.0\.0\.1:(\d+)->" + re.escape(internal) + r"/tcp", ports or "")
    return int(m.group(1)) if m else None


def discover() -> dict:
    projs = json.loads(subprocess.check_output(
        ["docker", "compose", "ls", "--all", "--format", "json"]).decode())
    cores = {}
    for pj in projs:
        proj = pj.get("Name", "")
        if not proj.endswith("-core"):
            continue
        compose_file = pj.get("ConfigFiles", "").split(",")[0]
        src = os.path.dirname(compose_file)
        rows = subprocess.check_output(
            ["docker", "ps", "--filter", f"label=com.docker.compose.project={proj}",
             "--format", '{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.Ports}}']).decode().splitlines()
        agent = next((r for r in rows if r.split("|")[0].endswith("-agent-costaff")), None)
        pg = next((r for r in rows if r.split("|")[0].endswith("-postgres")), None)
        if not agent:
            continue
        aname, aservice, aports = agent.split("|", 2)
        prefix = aname[:-len("-agent-costaff")]
        manager_port = _host_port(aports, "8080")
        pg_port = _host_port(pg.split("|", 2)[2], "5432") if pg else None

        # DB uri from this core's own .env, rewritten to host-reachable port
        db_uri = ""
        env_path = os.path.join(src, ".env")
        if os.path.exists(env_path):
            for ln in open(env_path):
                if ln.startswith("ADK_SESSION_SERVICE_URI"):
                    db_uri = ln.split("=", 1)[1].strip().strip("'\"")
                    break
        if db_uri and pg_port and "postgres:5432" in db_uri:
            db_uri = db_uri.replace("postgres:5432", f"localhost:{pg_port}")

        cores[prefix] = {
            "label": {"costaff": "Main", "asst": "Assistant", "twk": "Twinkle"}.get(prefix, prefix.title()),
            "container_prefix": prefix,
            "manager_port": manager_port or int(os.getenv("COSTAFF_AGENT_PORT", "18080")),
            "db_uri": db_uri,
            "config_path": os.path.join(src, "config.json"),
            "env_path": os.path.join(src, ".env"),
            "compose_file": compose_file,
            "compose_project": proj,
            "manager_service": aservice,
        }
    return cores
