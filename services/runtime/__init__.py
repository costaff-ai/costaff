"""Runtime factory: select the orchestration backend.

Usage:
    from services.runtime import get_runtime
    runtime = get_runtime()
    runtime.up(["postgres"])

Backend selection is controlled by COSTAFF_RUNTIME env var. The default
is "docker", which uses docker compose under the hood. Future backends
(k8s, remote HTTP) plug in here without CLI changes.
"""
import os

from .base import Runtime
from .docker import DockerRuntime

__all__ = ["Runtime", "DockerRuntime", "get_runtime", "runtime_for"]


def get_runtime() -> Runtime:
    """Return a Runtime instance for the configured backend."""
    backend = (os.getenv("COSTAFF_RUNTIME") or "docker").lower()
    if backend == "docker":
        return DockerRuntime()
    raise ValueError(
        f"Unknown COSTAFF_RUNTIME: {backend!r}. Supported: 'docker'."
    )


def runtime_for(core) -> Runtime:
    """Runtime bound to one core's compose file / project / cwd.

    The synthetic default core keeps `get_runtime()`'s path detection
    (identical to the historical behaviour); registered cores pin the
    compose file, project name, and cwd so container operations land on
    the right stack.
    """
    if core.is_default:
        return get_runtime()
    return DockerRuntime(
        compose_cwd=core.runtime_root,
        base_compose=core.main_compose,
        project=core.compose_project or None,
    )
