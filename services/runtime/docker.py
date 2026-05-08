"""Docker Compose backend for the Runtime interface.

All docker / docker-compose subprocess invocations live here. CLI code
should never construct a `["docker", ...]` argv directly — call
methods on a Runtime instance instead.
"""
import os
import subprocess
from typing import Dict, List, Optional

from utils.paths import _project_root, _runtime_root

from .base import Runtime


def _detect_compose_cwd(compose_file: str) -> str:
    """Locate the directory containing the base compose file.

    Prefers the runtime root (~/.costaff/costaff) when present; falls
    back to the project root for in-development checkouts.
    """
    if os.path.exists(os.path.join(_runtime_root, compose_file)):
        return _runtime_root
    return _project_root


class DockerRuntime(Runtime):
    """Runtime that drives docker / docker-compose via subprocess."""

    def __init__(
        self,
        compose_cwd: Optional[str] = None,
        base_compose: str = "docker-compose.yaml",
    ):
        self.base_compose = base_compose
        self.compose_cwd = compose_cwd or _detect_compose_cwd(base_compose)

    # ─────────── Helpers ───────────

    @staticmethod
    def _docker_cmd() -> list:
        """Resolve `docker compose` (v2) or `docker-compose` (v1)."""
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                check=True,
            )
            return ["docker", "compose"]
        except Exception:
            return ["docker-compose"]

    def _compose_args(self, fragment: Optional[str] = None) -> list:
        """Build the `-f base [-f fragment]` args for a compose call."""
        args = ["-f", self.base_compose]
        if fragment:
            args += ["-f", fragment]
        return args

    # ─────────── Service operations ───────────

    def up(
        self,
        services: List[str],
        *,
        fragment: Optional[str] = None,
        build: bool = False,
        force_recreate: bool = False,
        remove_orphans: bool = False,
    ) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["up", "-d"]
        if build:
            cmd.append("--build")
        if force_recreate:
            cmd.append("--force-recreate")
        if remove_orphans:
            cmd.append("--remove-orphans")
        cmd.extend(services)
        subprocess.run(cmd, check=True, cwd=self.compose_cwd)

    def stop(
        self,
        services: List[str],
        *,
        fragment: Optional[str] = None,
    ) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["stop"] + services
        subprocess.run(cmd, check=False, cwd=self.compose_cwd)

    def build(
        self,
        services: Optional[List[str]] = None,
        *,
        fragment: Optional[str] = None,
        no_cache: bool = False,
    ) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["build"]
        if no_cache:
            cmd.append("--no-cache")
        if services:
            cmd.extend(services)
        result = subprocess.run(cmd, cwd=self.compose_cwd)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose build failed (exit={result.returncode})")

    def down(
        self,
        *,
        fragment: Optional[str] = None,
        remove_orphans: bool = False,
    ) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["down"]
        if remove_orphans:
            cmd.append("--remove-orphans")
        subprocess.run(cmd, check=True, cwd=self.compose_cwd)

    def ps(self, *, fragment: Optional[str] = None) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["ps"]
        subprocess.run(cmd, check=True, cwd=self.compose_cwd)

    def logs(
        self,
        services: Optional[List[str]] = None,
        *,
        fragment: Optional[str] = None,
        tail: Optional[int] = None,
    ) -> None:
        cmd = self._docker_cmd() + self._compose_args(fragment) + ["logs"]
        if tail is not None:
            cmd.extend(["--tail", str(tail)])
        if services:
            cmd.extend(services)
        subprocess.run(cmd, check=True, cwd=self.compose_cwd)

    # ─────────── Container-level operations ───────────

    def is_running(self, container_names: List[str]) -> Dict[str, bool]:
        if not container_names:
            return {}
        cmd = (
            self._docker_cmd()[:1]  # just "docker", not "docker compose"
            + ["inspect", "-f", "{{.State.Running}}"]
            + container_names
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {n: False for n in container_names}
        states = result.stdout.strip().split("\n")
        # Pad/truncate to match the input length defensively
        states += ["false"] * (len(container_names) - len(states))
        return {
            name: (state.strip() == "true")
            for name, state in zip(container_names, states)
        }

    def force_remove_container(self, name: str) -> None:
        subprocess.run(["docker", "stop", name], capture_output=True)
        subprocess.run(["docker", "rm", name], capture_output=True)
