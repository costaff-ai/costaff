"""Port allocation for dynamically registered agents and channels.

Agents use 18100-18199. Channels use 18090-18099. Both ranges are local-only
host ports for health checks; container-to-container traffic uses the
internal docker network.
"""


def _next_available_port(conf: dict, reserved: set = None) -> int:
    """First free agent port. `reserved` adds ports claimed elsewhere —
    host ports are machine-global, so multi-core hosts must pass the union
    of every core's used ports (services.cores.all_used_public_ports)."""
    used = {a.get("public_port") for a in conf.get("external_agents", {}).values() if a.get("public_port")}
    used |= reserved or set()
    for p in range(18100, 18200):
        if p not in used:
            return p
    raise RuntimeError("No available ports in range 18100-18199")


def _next_available_channel_port(conf: dict, reserved: set = None) -> int:
    """First free channel port. `reserved` adds ports claimed elsewhere —
    host ports are machine-global, so multi-core hosts must pass the union
    of every core's used ports (services.cores.all_used_public_ports)."""
    used = {c.get("public_port") for c in conf.get("dynamic_channels", {}).values() if c.get("public_port")}
    used |= reserved or set()
    for p in range(18090, 18100):
        if p not in used:
            return p
    raise RuntimeError("No available ports in range 18090-18099")
