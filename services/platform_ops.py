"""Shared platform compose plumbing.

Single source of truth for platform dependency ordering and `docker compose`
invocation, used by BOTH the `costaff platform` CLI and the dashboard's
platforms router. Lives in services/ so the host-side FastAPI server can reuse
it without importing the CLI layer (which would create an import cycle via
cli/__init__ → cli.commands.dashboard → server.app).
"""
import os
import subprocess
from typing import List

DB_CONTAINER = "costaff-platform-postgres"
DB_NETWORK = "costaff_platform_db"


def start_order(platforms: dict) -> List[str]:
    """Shared DB first, Account Manager (IdP) second, the rest sorted."""
    names = list(platforms.keys())
    head = [n for n in ("db", "account-manager") if n in names]
    tail = sorted(n for n in names if n not in ("db", "account-manager"))
    return head + tail


def compose(src: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run `docker compose <args>` inside a platform's source dir (its .env is
    picked up automatically from the cwd)."""
    from services.docker import DockerManager

    cmd = DockerManager.get_cmd() + ["-f", os.path.join(src, "docker-compose.yaml")] + list(args)
    return subprocess.run(cmd, cwd=src, check=check)


def ensure_networks() -> None:
    """Create the shared external networks if they don't exist (idempotent)."""
    for net in ("costaff_default", DB_NETWORK):
        subprocess.run(
            ["docker", "network", "create", net],
            capture_output=True, check=False,
        )
