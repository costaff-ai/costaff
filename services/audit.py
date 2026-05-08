"""
Append-only audit log. Writes one JSON line per event to .costaff/audit.log.
Never raises — failures are swallowed so audit never breaks the main flow.
"""
import json
import logging
import os
import time
from typing import Any

from utils.paths import PATHS

logger = logging.getLogger(__name__)

_AUDIT_LOG = os.path.join(os.path.dirname(PATHS["auth"]), "audit.log")


def audit(action: str, **detail: Any) -> None:
    """Write one audit log entry.

    Usage:
        audit("agent.add", name="my-agent", url="http://...")
        audit("login.success", username="admin")
    """
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            **detail,
        }
        os.makedirs(os.path.dirname(_AUDIT_LOG), exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Audit log write failed: {e}")
