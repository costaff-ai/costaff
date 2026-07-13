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
import threading

from sqlalchemy import create_engine

from services.config import ConfigManager
from utils.paths import PATHS

DEFAULT_PREFIX = "costaff"

# SQLAlchemy engines own a connection pool and are meant to be long-lived and
# shared. `active_core()` builds a fresh CoreContext per request, so caching on
# the instance would not help; cache engines module-wide keyed by resolved URI.
# Without this, every dashboard request (incl. the 5s pollers) created a new
# engine that was never .dispose()'d -> connections leaked until GC and the
# shared Postgres eventually refused new connections.
_ENGINES: dict = {}
_ENGINES_LOCK = threading.Lock()


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

    # --- derived filesystem layout (mirrors the ~/.costaff convention:
    #     <base>/costaff/config.json, <base>/costaff-agent/, <base>/workspace/) ---
    @property
    def runtime_root(self) -> str:
        return os.path.dirname(self.config_path)

    @property
    def base_dir(self) -> str:
        return os.path.dirname(self.runtime_root)

    @property
    def workspace_root(self) -> str:
        return os.path.join(self.base_dir, "workspace")

    @property
    def main_compose(self) -> str:
        return self.compose_file or os.path.join(self.runtime_root, "docker-compose.yaml")

    @property
    def is_default(self) -> bool:
        """True for the synthetic single-install core (no registry entry)."""
        return self.name == "default"

    @property
    def network_name(self) -> str:
        """The docker network agents/channels on this core must join.

        Read from the core's base compose `networks.default.name` — a
        non-default core (e.g. asst → costaff_asst, twk → costaff_twk) runs
        on its own network, so a plugin fragment hardcoding costaff_default
        would land the container on the wrong network and the manager could
        not reach it. Falls back to costaff_default (the single-install
        network) when the compose can't be read."""
        try:
            import yaml
            with open(self.main_compose) as f:
                compose = yaml.safe_load(f) or {}
            name = (compose.get("networks", {}).get("default", {}) or {}).get("name")
            if name:
                return name
        except Exception:
            pass
        return "costaff_default"

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
        cached = _ENGINES.get(uri)
        if cached is not None:
            return cached
        with _ENGINES_LOCK:
            cached = _ENGINES.get(uri)  # re-check inside lock (avoid dup build)
            if cached is not None:
                return cached
            try:
                # pool_recycle drops connections Postgres may have closed while
                # idle; pool_pre_ping validates a connection before handing it out.
                eng = create_engine(uri, pool_pre_ping=True, pool_recycle=1800)
            except Exception:
                return None
            _ENGINES[uri] = eng
            return eng

    # --- this core's own config.json (external_agents / channels / mcp / filters) ---
    def core_config(self) -> dict:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path) as f:
                return json.load(f)
        except (ValueError, OSError) as e:
            # Corrupt config must be loud — a silent {} here gets written
            # back by the next save and wipes this core's registrations.
            raise RuntimeError(
                f"{self.config_path} is unreadable ({e}) — fix or restore "
                "it before continuing."
            ) from e

    # --- writes (Full / per-core) ---
    def write_config(self, conf: dict):
        ConfigManager.save_config(conf, self.config_path)

    def regen_external_agents_env(self):
        ConfigManager.update_external_agents_env(self.config_path, self.env_path)

    def regen_mcp_urls(self):
        ConfigManager.update_mcp_urls(self.config_path, self.env_path, self.prefix)

    def recreate_manager(self) -> bool:
        """Recreate ONLY the manager container so it reloads regenerated env.

        Uses `docker compose up -d --force-recreate --no-deps <service>` scoped to
        this core's compose project. Falls back to a plain restart for the
        synthetic single-core default (no compose metadata). Returns True on
        success; a False return lets callers warn instead of printing "Done"
        over a silent failure (the manager would keep running stale env)."""
        import subprocess
        from services.docker import DockerManager
        if self.compose_file and self.compose_project:
            cmd = (DockerManager.get_cmd()
                   + ["-p", self.compose_project, "-f", self.compose_file,
                      "up", "-d", "--force-recreate", "--no-deps", self.manager_service])
            res = subprocess.run(cmd, cwd=os.path.dirname(self.compose_file))
            return res.returncode == 0
        try:
            DockerManager.run_action(self.cn("agent-costaff"), "restart")  # raises on failure
            return True
        except Exception:
            return False

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


def get_core(name: str = None) -> CoreContext:
    """Resolve a core by name; None → the active core (CLI --core semantics)."""
    cores, active = _registry()
    target = name or active
    if target not in cores:
        raise ValueError(f"unknown core '{target}' (known: {', '.join(sorted(cores))})")
    return CoreContext(target, cores[target])


def all_used_public_ports() -> set:
    """Public ports claimed by agents/channels across EVERY registered core.

    Host ports are machine-global, so allocation on one core must not
    collide with entries registered on another core's config.json.
    """
    cores, _ = _registry()
    used = set()
    for name, data in cores.items():
        try:
            conf = CoreContext(name, data).core_config()
        except Exception as e:
            # One core's corrupt/unreadable config.json must not block port
            # allocation on a DIFFERENT core. Skip it (its ports simply aren't
            # reserved — worst case is a collision the operator will see and
            # fix by repairing that core), rather than crashing every deploy.
            import warnings
            warnings.warn(f"skipping core {name!r} for port reservation: {e}", stacklevel=2)
            continue
        for section in ("external_agents", "dynamic_channels"):
            for entry in conf.get(section, {}).values():
                if entry.get("public_port"):
                    used.add(entry["public_port"])
    return used


def set_active(name: str) -> str:
    conf = ConfigManager.get_config()
    cores = conf.get("cores") or {}
    # Validate against the real registry even on single-install hosts (no
    # `cores` key): there the only valid target is the synthetic "default"
    # core, so anything else is a typo that would otherwise be silently
    # written as an invalid active_core.
    valid = set(cores) if cores else {"default"}
    if name not in valid:
        raise ValueError(f"unknown core '{name}' (known: {', '.join(sorted(valid))})")
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
