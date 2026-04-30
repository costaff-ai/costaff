"""Runtime factory: select the orchestration backend.

Usage:
    from managers.runtime import get_runtime
    runtime = get_runtime()
    runtime.up(["postgres"])

Backend selection is controlled by COSTAFF_RUNTIME env var. The default
is "docker", which uses docker compose under the hood. Future backends
(k8s, remote HTTP) plug in here without CLI changes.
"""
import os

from .base import Runtime
from .docker import DockerRuntime

__all__ = ["Runtime", "DockerRuntime", "get_runtime"]


def get_runtime() -> Runtime:
    """Return a Runtime instance for the configured backend."""
    backend = (os.getenv("COSTAFF_RUNTIME") or "docker").lower()
    if backend == "docker":
        return DockerRuntime()
    raise ValueError(
        f"Unknown COSTAFF_RUNTIME: {backend!r}. Supported: 'docker'."
    )
