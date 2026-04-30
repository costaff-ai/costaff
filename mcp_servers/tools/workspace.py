import os
import shutil
from pathlib import Path
from typing import Optional

from mcp_servers.core import mcp

_DATA_ROOT = Path(os.getenv("WORKSPACE_DIR", "/app/data"))


@mcp.tool()
def move_to_shared(src_path: str, overwrite: bool = False) -> str:
    """
    Copy a file or directory from an agent's private workspace to the shared workspace.
    src_path: absolute path inside /app/data (e.g. /app/data/costaff-agent-coding/report.pdf)
    The item is mirrored under /app/data/shared/ preserving its relative path after /app/data/.
    Use overwrite=True to replace an existing destination.
    """
    src = Path(src_path).resolve()
    data_root = _DATA_ROOT.resolve()

    if not str(src).startswith(str(data_root) + "/"):
        return f"[ERROR] src_path must be under {data_root}"
    if not src.exists():
        return f"[ERROR] Source not found: {src}"

    rel = src.relative_to(data_root)
    dst = data_root / "shared" / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and not overwrite:
        return f"[WARN] Destination already exists: {dst}. Use overwrite=True to replace."

    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)

    return f"[OK] Copied {src} → {dst}"


@mcp.tool()
def list_data_files(path: str, pattern: Optional[str] = None) -> str:
    """
    List files under a path inside /app/data. Use this to verify output files exist
    before marking a task as done.

    Renamed from list_workspace to avoid name collision with the
    business_analysis agent's own list_workspace(subdir) tool, which is a
    different function with a different signature.

    - path: absolute path under /app/data (e.g. /app/data/shared/costaff-agent-coding)
    - pattern: optional filename filter, e.g. "*.pdf" or "report.csv"

    Returns a newline-separated list of absolute file paths found, or an error message.
    Also accepts a full file path — returns "[EXISTS] <path>" or "[NOT FOUND] <path>".
    """
    target = Path(path).resolve()
    data_root = _DATA_ROOT.resolve()

    if not str(target).startswith(str(data_root)):
        return f"[ERROR] path must be under {data_root}"

    # Single file check
    if target.is_file():
        return f"[EXISTS] {target}"

    # Check if it looks like a file path (has extension) but doesn't exist
    if target.suffix and not target.exists():
        return f"[NOT FOUND] {target}"

    if not target.exists():
        return f"[NOT FOUND] {target}"

    glob_pattern = pattern if pattern else "*"
    files = sorted(target.rglob(glob_pattern))
    files = [f for f in files if f.is_file()]

    if not files:
        return f"[EMPTY] No files found under {target}" + (f" matching '{pattern}'" if pattern else "")

    return "\n".join(str(f) for f in files)
