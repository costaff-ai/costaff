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

VERSION = "0.1.0-alpha-1"

PATHS = {
    "env":      os.path.join(_runtime_root, ".env"),
    "config":   os.path.join(_runtime_root, "config.json"),
    "auth":     os.path.join(_runtime_root, "auth.json"),
    "frontend": os.path.join(_project_root, "frontend"),
}
