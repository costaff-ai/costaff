"""Git operations for the costaff CLI.

CLI commands should not call `subprocess.run(["git", ...])` directly —
they go through this thin wrapper so that error messages stay consistent
("git binary not found" vs "clone failed: <stderr>") and a future
non-subprocess implementation (e.g. dulwich for sandboxed environments)
can swap in without touching callers.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


class GitError(RuntimeError):
    """Any git operation that did not complete successfully."""


class Git:
    def is_repo(self, path: PathLike) -> bool:
        return (Path(path) / ".git").is_dir()

    def clone(
        self,
        url: str,
        dest: PathLike,
        *,
        depth: int = 1,
        ref: Optional[str] = None,
    ) -> None:
        """Clone `url` into `dest`.

        - `depth=1` keeps the default shallow clone (the historical
          behaviour of this wrapper). Pass `depth=0` to clone the full
          history.
        - `ref` pins the working tree to a branch or tag. Internally we
          pass `--branch <ref>` to `git clone`; git accepts both branch
          and tag names there. When pinned to a tag, the working tree
          ends up in detached-HEAD state — that's intentional, the CLI
          uses `checkout()` afterwards to move between refs.
        """
        cmd = ["git", "clone"]
        if depth:
            cmd += ["--depth", str(depth)]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(dest)]
        self._run(cmd)

    def pull_ff_only(self, repo: PathLike) -> None:
        self._run(["git", "pull", "--ff-only"], cwd=str(repo))

    def fetch_tags(self, repo: PathLike) -> None:
        """Fetch refs + tags from origin without merging anything. Used
        before `checkout(<tag>)` so a freshly cloned shallow repo can
        actually find the tag on the remote."""
        self._run(
            ["git", "fetch", "--tags", "--prune", "origin"],
            cwd=str(repo),
        )

    def checkout(self, repo: PathLike, ref: str) -> None:
        """Check out `ref` (branch name, tag name, or commit SHA) in
        `repo`. Working tree ends up in detached HEAD if `ref` is a tag
        or SHA — that's expected for a pinned deployment."""
        self._run(["git", "checkout", ref], cwd=str(repo))

    def list_remote_tags(self, repo: PathLike) -> list[str]:
        """Return tag names visible on `origin`, freshest first.

        Uses `git ls-remote --tags origin` so the local repo doesn't
        need a prior fetch. The peeled refs (`<tag>^{}`) returned by
        ls-remote are deduped — only the symbolic tag name appears in
        the result. Sorted by version-ish ordering (newest first); we
        rely on `git`'s `--sort=-v:refname` for that.
        """
        try:
            out = self._run_capture(
                ["git", "-c", "versionsort.suffix=-", "ls-remote",
                 "--tags", "--refs", "--sort=-v:refname", "origin"],
                cwd=str(repo),
            )
        except GitError:
            # An empty remote, missing auth, or no tags at all — let the
            # caller decide whether that's an error vs an empty list.
            raise
        tags: list[str] = []
        for line in out.splitlines():
            # Each line is "<sha>\trefs/tags/<name>"; we want <name>.
            _, _, ref = line.partition("\t")
            if ref.startswith("refs/tags/"):
                tags.append(ref[len("refs/tags/"):])
        return tags

    def current_ref(self, repo: PathLike) -> str:
        """Return whatever HEAD points at: a branch name if attached,
        otherwise the tag closest to HEAD, else the abbreviated SHA. The
        CLI uses this for the `agent list` / `channel list` output."""
        # If HEAD is attached to a branch, `symbolic-ref --short` succeeds.
        try:
            out = self._run_capture(
                ["git", "symbolic-ref", "--short", "HEAD"], cwd=str(repo)
            )
            return out.strip()
        except GitError:
            pass
        # Detached HEAD. Try exact tag, fall back to short SHA.
        try:
            out = self._run_capture(
                ["git", "describe", "--tags", "--exact-match", "HEAD"],
                cwd=str(repo),
            )
            return out.strip()
        except GitError:
            pass
        out = self._run_capture(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(repo)
        )
        return out.strip()

    @staticmethod
    def _run(cmd: list[str], *, cwd: str | None = None) -> None:
        try:
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise GitError(
                "git binary not found in PATH. Install git and retry."
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or "(no output)"
            raise GitError(f"{' '.join(cmd)} failed: {stderr}") from e

    @staticmethod
    def _run_capture(cmd: list[str], *, cwd: str | None = None) -> str:
        try:
            result = subprocess.run(
                cmd, cwd=cwd, check=True, capture_output=True, text=True
            )
            return result.stdout
        except FileNotFoundError as e:
            raise GitError(
                "git binary not found in PATH. Install git and retry."
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or "(no output)"
            raise GitError(f"{' '.join(cmd)} failed: {stderr}") from e
