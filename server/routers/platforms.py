"""Dashboard router for business platforms (ERP/CRM/HRM/…).

Two kinds of platform entry live in config.json `platforms`:

- **local**  — installed on this host via `costaff platform add` (compose
  project, `source_path` set). Listed with localhost health + start/stop/
  restart. Deployment-level operations (add / rebuild / remove / tag-pin)
  stay CLI-only for these.
- **remote** — registered from the dashboard's store flow (`type: "remote"`,
  a user-supplied `url`, optional `mcp_url`). No compose management; health
  probes the stored URL. Full CRUD lives here.

Compose helpers are the SAME ones the CLI uses (`start_order`, `compose`,
`ensure_networks`) so dependency order stays a single source of truth.
"""
import logging
import re
import subprocess
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Depends

from services.auth import AuthManager
from services.config import ConfigManager
from services.audit import audit
from server.schemas import PlatformRegisterRequest, PlatformUpdateRequest, ServiceActionRequest
from services.platform_ops import start_order, compose, ensure_networks
from services.platform_registry import OFFICIAL_PLATFORMS

logger = logging.getLogger(__name__)
router = APIRouter()

SHARED_DB = "db"  # pseudo-platform every other platform depends on

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _is_remote(info: dict) -> bool:
    return info.get("type") == "remote" or (not info.get("source_path") and bool(info.get("url")))


def _probe(url: str) -> str:
    try:
        r = httpx.get(url, timeout=3.0, follow_redirects=True)
        return "healthy" if r.status_code < 500 else "unhealthy"
    except Exception:
        return "down"


def _health(info: dict) -> str:
    """Frontend reachability — mirrors `costaff platform list` for local
    entries; remote entries probe their registered URL."""
    if not info.get("enabled", True):
        return "n/a"
    if _is_remote(info):
        return _probe(info["url"]) if info.get("url") else "n/a"
    port = info.get("public_port")
    return _probe(f"http://localhost:{port}/") if port else "n/a"


def _validate_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"Invalid URL '{url}' — must be http(s)://host[:port]")
    return url


@router.get("/api/platforms")
def list_platforms(auth: bool = Depends(AuthManager.verify_token)):
    """Registered platforms in dependency order, with frontend health."""
    platforms = ConfigManager.get_config().get("platforms", {})
    out = []
    for name in start_order(platforms):
        info = platforms[name]
        remote = _is_remote(info)
        port = info.get("public_port")
        catalog = OFFICIAL_PLATFORMS.get(name, {})
        out.append({
            "name": name,
            "type": "remote" if remote else "local",
            "ref": info.get("ref"),
            "port": port,
            "enabled": bool(info.get("enabled", True)),
            "health": _health(info),
            "url": info.get("url") if remote else (f"http://localhost:{port}" if port else None),
            "mcp_url": info.get("mcp_url"),
            "description": info.get("description") or catalog.get("description"),
            "icon": catalog.get("icon"),
            "containers": info.get("container_names", []),
            "is_shared_db": name == SHARED_DB,
        })
    return out


@router.get("/api/platforms/catalog")
def platform_catalog(auth: bool = Depends(AuthManager.verify_token)):
    """The official platform store shelf, flagged with what's already registered."""
    registered = set(ConfigManager.get_config().get("platforms", {}).keys())
    return [
        {
            "name": name,
            "description": meta["description"],
            "icon": meta["icon"],
            "default_port": meta["port"],
            "registered": name in registered,
        }
        for name, meta in OFFICIAL_PLATFORMS.items()
        if meta["port"] is not None  # infra without a web frontend (shared db) isn't storefront material
    ]


@router.post("/api/platforms")
def register_platform(req: PlatformRegisterRequest, auth: bool = Depends(AuthManager.verify_token)):
    """Register a remote (URL-only) platform — the store's 'set URL and go' flow."""
    name = (req.name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Name must be lowercase letters, digits or dashes.")
    conf = ConfigManager.get_config()
    platforms = conf.setdefault("platforms", {})
    if name in platforms:
        raise HTTPException(status_code=409, detail=f"Platform '{name}' is already registered.")
    entry = {
        "type": "remote",
        "url": _validate_url(req.url),
        "enabled": True,
    }
    if req.mcp_url:
        entry["mcp_url"] = _validate_url(req.mcp_url)
    if req.description:
        entry["description"] = req.description.strip()
    platforms[name] = entry
    ConfigManager.save_config(conf)
    audit("platform.register", name=name, url=entry["url"])
    return {"status": "success", "name": name}


@router.put("/api/platforms/{name}")
def update_platform(name: str, req: PlatformUpdateRequest,
                    auth: bool = Depends(AuthManager.verify_token)):
    """Edit a remote platform's URL / MCP URL / description / enabled flag."""
    conf = ConfigManager.get_config()
    platforms = conf.get("platforms", {})
    if name not in platforms:
        raise HTTPException(status_code=404, detail=f"Platform '{name}' not found.")
    info = platforms[name]
    if not _is_remote(info):
        raise HTTPException(status_code=400,
                            detail=f"'{name}' is installed locally — manage it with the costaff CLI.")
    changes = req.dict(exclude_unset=True)
    if "url" in changes:
        info["url"] = _validate_url(changes["url"])
    if "mcp_url" in changes:
        info["mcp_url"] = _validate_url(changes["mcp_url"]) if changes["mcp_url"] else None
        if info["mcp_url"] is None:
            info.pop("mcp_url", None)
    if "description" in changes:
        info["description"] = (changes["description"] or "").strip() or None
        if info["description"] is None:
            info.pop("description", None)
    if "enabled" in changes:
        info["enabled"] = bool(changes["enabled"])
    ConfigManager.save_config(conf)
    audit("platform.update", name=name, changes=changes)
    return {"status": "success"}


@router.delete("/api/platforms/{name}")
def remove_platform(name: str, auth: bool = Depends(AuthManager.verify_token)):
    """Unregister a remote platform. Local installs must go through the CLI
    (`costaff platform remove`) because containers/volumes need tearing down."""
    conf = ConfigManager.get_config()
    platforms = conf.get("platforms", {})
    if name not in platforms:
        raise HTTPException(status_code=404, detail=f"Platform '{name}' not found.")
    if not _is_remote(platforms[name]):
        raise HTTPException(status_code=400,
                            detail=f"'{name}' is installed locally — remove it with `costaff platform remove {name}`.")
    del platforms[name]
    ConfigManager.save_config(conf)
    audit("platform.remove", name=name)
    return {"status": "success"}


@router.post("/api/platforms/{name}/action")
def platform_action(name: str, req: ServiceActionRequest,
                    auth: bool = Depends(AuthManager.verify_token)):
    """start / stop / restart a single platform's compose project."""
    platforms = ConfigManager.get_config().get("platforms", {})
    if name not in platforms:
        raise HTTPException(status_code=404, detail=f"Platform '{name}' not found.")
    if _is_remote(platforms[name]):
        raise HTTPException(status_code=400,
                            detail=f"'{name}' is a remote platform — its lifecycle is managed on its own host.")
    src = platforms[name].get("source_path")
    if not src:
        raise HTTPException(status_code=400, detail=f"Platform '{name}' has no source_path.")

    action = req.action
    try:
        if action == "start":
            ensure_networks()
            compose(src, "up", "-d")
        elif action == "restart":
            compose(src, "restart")
        elif action == "stop":
            # Refuse to pull the shared DB out from under live dependants.
            if name == SHARED_DB:
                dependants = [n for n, i in platforms.items()
                              if n != SHARED_DB and i.get("enabled", True)]
                if dependants:
                    raise HTTPException(
                        status_code=400,
                        detail="Other platforms depend on the shared DB; stop them first: "
                               + ", ".join(sorted(dependants)),
                    )
            compose(src, "down")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action '{action}'.")
    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        logger.exception("platform action failed name=%s action=%s", name, action)
        raise HTTPException(status_code=500, detail=f"compose {action} failed: {e}")
    except Exception as e:
        logger.exception("platform action failed name=%s action=%s", name, action)
        raise HTTPException(status_code=500, detail=str(e))

    audit(f"platform.{action}", name=name)
    return {"status": "success"}
