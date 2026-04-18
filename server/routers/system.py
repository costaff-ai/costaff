import os
import sys
import time
import subprocess
import threading
from datetime import date
from typing import Optional

import psutil
from fastapi import APIRouter, HTTPException, Depends
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from managers.auth import AuthManager
from managers.config import ConfigManager
from managers.docker import DockerManager
from managers.database import DatabaseManager
from models.requests import ServiceActionRequest
from utils.helpers import PATHS, _project_root, _runtime_root, _runtime_root

router = APIRouter()


@router.get("/api/status")
def get_status(auth: bool = Depends(AuthManager.verify_token)):
    res = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"], capture_output=True, text=True)
    return [{"name": p[0], "status": p[1], "image": p[2]} for line in res.stdout.splitlines() if (p := line.split("\t")) and len(p) >= 3 and any(k in p[0] for k in ["costaff", "mcp", "bot", "postgres", "gpt-vis"])]


@router.get("/api/os-stats")
def get_os_stats(auth: bool = Depends(AuthManager.verify_token)):
    return {"cpu": psutil.cpu_percent(), "memory": psutil.virtual_memory().percent, "disk": psutil.disk_usage('/').percent, "uptime": int(time.time() - psutil.boot_time())}


@router.get("/api/license")
def get_license(auth: bool = Depends(AuthManager.verify_token)):
    sys.path.insert(0, _project_root)
    from src.core.license import LicenseManager, OSS_LIMITS
    costaff_dir = _runtime_root
    license_path = os.path.join(costaff_dir, "costaff-license.yaml")

    def _monthly_used() -> int:
        try:
            engine = DatabaseManager.get_engine()
            if not engine:
                return 0
            month_start = date.today().replace(day=1).isoformat()
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM regular_work_logs WHERE status = 'success' AND created_at >= :ms"),
                    {"ms": month_start}
                )
                return result.scalar() or 0
        except Exception:
            return 0

    def _current_usage() -> dict:
        conf = ConfigManager.get_config()
        # extra_mcp: count external MCPs that are enabled
        ext = conf.get("external_mcp", {})
        used_mcp = sum(1 for v in ext.values() if (v.get("enabled", True) if isinstance(v, dict) else True))
        # users: count rows in user_contacts
        used_users = 0
        try:
            engine = DatabaseManager.get_engine()
            if engine:
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT COUNT(*) FROM identity_maps WHERE is_approved = true"))
                    used_users = result.scalar() or 0
        except Exception:
            pass
        # channels: count explicitly enabled channels in config
        used_channels = len(conf.get("channels", []))
        # apis and skills: count rows in their tables
        used_apis = 0
        used_skills = 0
        try:
            engine = DatabaseManager.get_engine()
            if engine:
                with engine.connect() as conn:
                    used_apis   = conn.execute(text("SELECT COUNT(*) FROM api_configs")).scalar() or 0
                    used_skills = conn.execute(text("SELECT COUNT(*) FROM skill_configs")).scalar() or 0
        except Exception:
            pass
        return {
            "monthly_executions": _monthly_used(),
            "extra_mcp":          used_mcp,
            "users":              used_users,
            "enabled_channels":   used_channels,
            "apis":               used_apis,
            "skills":             used_skills,
        }

    try:
        info = LicenseManager.load(license_path)
        if info:
            return {
                "plan":         info.plan,
                "issued_to":    info.issued_to,
                "expires_at":   str(info.expires_at) if info.expires_at else None,
                "is_expired":   info.is_expired,
                "limits": {
                    "extra_mcp":          info.extra_mcp,
                    "monthly_executions": info.monthly_executions,
                    "max_users":          info.max_users,
                    "enabled_channels":   info.enabled_channels,
                    "max_apis":           info.max_apis,
                    "max_skills":         info.max_skills,
                },
                "usage": _current_usage(),
            }
    except ValueError as e:
        return {"plan": "invalid", "error": str(e)}
    return {
        "plan":      "oss",
        "issued_to": None,
        "expires_at": None,
        "is_expired": False,
        "limits":    OSS_LIMITS,
        "usage":     _current_usage(),
    }


@router.post("/api/services/{service}/action")
def service_action(service: str, req: ServiceActionRequest, auth: bool = Depends(AuthManager.verify_token)):
    if req.action == "stop" and service in ["mcp-costaff", "costaff-agent", "postgres"]:
        raise HTTPException(status_code=400, detail="Cannot stop core service.")
    try:
        DockerManager.run_action(service, req.action)
        # Sync channels list when bot services are started/stopped
        bot_map = {"bot-telegram": "tg", "bot-discord": "dc", "bot-line": "line"}
        if service in bot_map:
            ch_id = bot_map[service]
            conf = ConfigManager.get_config()
            channels = conf.get("channels", [])
            if req.action == "start" and ch_id not in channels:
                channels.append(ch_id)
                conf["channels"] = channels
                ConfigManager.save_config(conf)
            elif req.action == "stop" and ch_id in channels:
                conf["channels"] = [c for c in channels if c != ch_id]
                ConfigManager.save_config(conf)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/config/require-approval")
def set_require_approval(req: dict, auth: bool = Depends(AuthManager.verify_token)):
    # Approval gate is an Enterprise-only feature
    costaff_dir = _runtime_root
    license_path = os.path.join(costaff_dir, "costaff-license.yaml")
    if not os.path.exists(license_path):
        raise HTTPException(status_code=403, detail="User approval gate is an Enterprise feature. OSS installations cannot enable this setting.")
    conf = ConfigManager.get_config()
    conf["require_approval"] = bool(req.get("enabled", True))
    ConfigManager.save_config(conf)
    return {"status": "ok", "require_approval": conf["require_approval"]}
