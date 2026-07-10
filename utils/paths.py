"""Filesystem layout constants for the CoStaff CLI runtime.

- `_project_root` — source code directory (git clone at ~/.costaff/costaff)
- `_base_dir` — runtime parent directory (~/.costaff); override via COSTAFF_HOME
- `_runtime_root` — CLI core + config + compose (~/.costaff/costaff)
- `_workspace_root` — bind-mounted data directory (~/.costaff/workspace)
"""
import os
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_base_dir: str = os.environ.get("COSTAFF_HOME") or str(Path.home() / ".costaff")
_runtime_root: str = os.path.join(_base_dir, "costaff")
_workspace_root: str = os.path.join(_base_dir, "workspace")

def _read_version() -> str:
    """Single source of truth: the VERSION file at the repo root ("vX.Y.Z…").

    setup.py reads the same file, so the CLI banner and pip metadata can
    never drift apart again.
    """
    try:
        with open(os.path.join(_project_root, "VERSION")) as f:
            return f.read().strip().removeprefix("v")
    except OSError:
        return "0.0.0+unknown"


VERSION = _read_version()

PATHS = {
    "env":      os.path.join(_runtime_root, ".env"),
    "config":   os.path.join(_runtime_root, "config.json"),
    "auth":     os.path.join(_runtime_root, "auth.json"),
    "frontend": os.path.join(_project_root, "frontend"),
}
