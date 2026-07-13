"""Input validators for cron expressions and external A2A URLs."""
import ipaddress
import re
import socket
from urllib.parse import urlparse


_CRON_PATTERN = re.compile(
    r'^(\*|[0-9*/,\-]+)\s+'    # minute
    r'(\*|[0-9*/,\-]+)\s+'     # hour
    r'(\*|[0-9?*/,\-L]+)\s+'   # day-of-month
    r'(\*|[0-9*/,\-]+)\s+'     # month
    r'(\*|[0-9?*/,\-L]+)$'     # day-of-week
)


def _validate_cron(cron: str) -> None:
    """Raises ValueError if the cron expression is not a valid 5-field format."""
    if not _CRON_PATTERN.match(cron.strip()):
        raise ValueError(
            f"Invalid cron expression: '{cron}'. "
            "Expected 5 fields: minute hour day-of-month month day-of-week"
        )


_BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", ""}

# The genuinely dangerous SSRF targets: loopback (localhost services) and the
# link-local / cloud-metadata range (169.254.0.0/16, incl. 169.254.169.254).
# Private LAN ranges (10/172.16/192.168) are deliberately NOT blocked —
# internal agents and enterprise-federation nodes legitimately live there.
_DANGEROUS_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_a2a_url(url: str) -> None:
    """Raises ValueError if the URL is not a safe external http/https endpoint."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("Invalid URL format")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    hostname = (parsed.hostname or "").lower()
    if hostname in _BLOCKED_HOSTNAMES:
        raise ValueError(f"URL hostname '{hostname}' is not allowed")
    # Resolve and reject a hostname that maps to loopback or the metadata /
    # link-local range — the literal blocklist alone misses a custom domain
    # that resolves there (DNS rebinding / SSRF). A transient resolution
    # failure does not block registration.
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except Exception:
        return
    for item in resolved:
        try:
            ip = ipaddress.ip_address(item[4][0])
        except ValueError:
            continue
        if any(ip in net for net in _DANGEROUS_NETWORKS):
            raise ValueError(
                f"URL hostname '{hostname}' resolves to a blocked address ({ip})"
            )
