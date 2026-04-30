"""Abstract Runtime interface — orchestration backend for the costaff CLI.

Implementations encapsulate all knowledge of how services are started,
stopped, built, and inspected. The CLI never imports docker / kubectl /
etc. directly; it talks to a Runtime instance.

The default implementation is DockerRuntime (managers/runtime/docker.py).
Future implementations may include KubernetesRuntime, RemoteRuntime
(HTTP API to a remote control plane), or a process-based runtime.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class Runtime(ABC):
    """Container orchestration runtime interface."""

    # ─────────── Service operations (compose / k8s aware) ───────────

    @abstractmethod
    def up(
        self,
        services: List[str],
        *,
        fragment: Optional[str] = None,
        build: bool = False,
        force_recreate: bool = False,
        remove_orphans: bool = False,
    ) -> None:
        """Start (and optionally build) one or more services."""

    @abstractmethod
    def stop(
        self,
        services: List[str],
        *,
        fragment: Optional[str] = None,
    ) -> None:
        """Stop services without removing them."""

    @abstractmethod
    def build(
        self,
        services: Optional[List[str]] = None,
        *,
        fragment: Optional[str] = None,
        no_cache: bool = False,
    ) -> None:
        """Build images. Raises RuntimeError if the build fails."""

    @abstractmethod
    def down(
        self,
        *,
        fragment: Optional[str] = None,
        remove_orphans: bool = False,
    ) -> None:
        """Stop and remove all services in the compose project."""

    @abstractmethod
    def ps(self, *, fragment: Optional[str] = None) -> None:
        """Print compose status to stdout."""

    @abstractmethod
    def logs(
        self,
        services: Optional[List[str]] = None,
        *,
        fragment: Optional[str] = None,
        tail: Optional[int] = None,
    ) -> None:
        """Stream/print logs to stdout."""

    # ─────────── Container-level operations ───────────

    @abstractmethod
    def is_running(self, container_names: List[str]) -> Dict[str, bool]:
        """Check whether each named container is currently running.

        Returns a dict mapping container name → True/False.
        Missing containers map to False.
        """

    @abstractmethod
    def force_remove_container(self, name: str) -> None:
        """Best-effort stop + remove of a single container by name."""

    # ─────────── Default convenience composed of the above ───────────

    def restart(
        self,
        services: List[str],
        *,
        fragment: Optional[str] = None,
        force_recreate: bool = True,
    ) -> None:
        """Stop then up — used to ensure env vars are reloaded."""
        self.stop(services, fragment=fragment)
        self.up(services, fragment=fragment, force_recreate=force_recreate)
