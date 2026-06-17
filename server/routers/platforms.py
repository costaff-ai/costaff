"""Dashboard router for business platforms (ERP/CRM/HRM/…).

Read-only listing + per-platform start/stop/restart. Reuses the SAME helpers
the `costaff platform` CLI uses (`_start_order`, `_compose`, `_ensure_networks`)
so dependency order and compose plumbing stay a single source of truth.

Deployment-level operations (add / rebuild / remove / tag-pin) intentionally
stay CLI-only; the dashboard is an ops console.
"""
import logging
import subprocess

import httpx
from fastapi import APIRouter, HTTPException, Depends

from services.auth import AuthManager
from services.config import ConfigManager
from services.audit import audit
from server.schemas import ServiceActionRequest
from services.platform_ops import start_order, compose, ensure_networks

logger = logging.getLogger(__name__)
router = APIRouter()

SHARED_DB = "db"  # pseudo-platform every other platform depends on


def _health(port, enabled) -> str:
    """Frontend reachability — mirrors `costaff platform list`."""
    if not port or not enabled:
        return "n/a"
    try:
        r = httpx.get(f"http://localhost:{port}/", timeout=3.0, follow_redirects=True)
        return "healthy" if r.status_code < 500 else "unhealthy"
    except Exception:
        return "down"


@router.get("/api/platforms")
def list_platforms(auth: bool = Depends(AuthManager.verify_token)):
    """Registered platforms in dependency order, with frontend health."""
    platforms = ConfigManager.get_config().get("platforms", {})
    out = []
    for name in start_order(platforms):
        info = platforms[name]
        port = info.get("public_port")
        enabled = bool(info.get("enabled", True))
        out.append({
            "name": name,
            "ref": info.get("ref"),
            "port": port,
            "enabled": enabled,
            "health": _health(port, enabled),
            "url": f"http://localhost:{port}" if port else None,
            "containers": info.get("container_names", []),
            "is_shared_db": name == SHARED_DB,
        })
    return out


@router.post("/api/platforms/{name}/action")
def platform_action(name: str, req: ServiceActionRequest,
                    auth: bool = Depends(AuthManager.verify_token)):
    """start / stop / restart a single platform's compose project."""
    platforms = ConfigManager.get_config().get("platforms", {})
    if name not in platforms:
        raise HTTPException(status_code=404, detail=f"Platform '{name}' not found.")
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
