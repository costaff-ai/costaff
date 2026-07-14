"""Channel deploy helpers must be core-aware (parity with agents).

Covers the host-side, docker-free surface of `channel --core`:
- _next_available_channel_port honours cross-core reserved ports.
- _write_channel_fragment stamps the core's container prefix, workspace,
  and env file — and, with core=None, is byte-for-byte the historical
  single-install layout (prefix "costaff", global paths).
"""
import os

import yaml

from utils.ports import _next_available_channel_port
from utils.compose import _write_channel_fragment


# ---------------------------------------------------------------------------
# port reservation across cores
# ---------------------------------------------------------------------------

def test_channel_port_skips_reserved():
    conf = {"dynamic_channels": {"a": {"public_port": 18090}}}
    # 18090 used in conf, 18091 reserved by another core → first free is 18092
    assert _next_available_channel_port(conf, reserved={18091}) == 18092


def test_channel_port_without_reserved_unchanged():
    assert _next_available_channel_port({"dynamic_channels": {}}) == 18090


# ---------------------------------------------------------------------------
# fragment generation — prefix / workspace / env come from the core
# ---------------------------------------------------------------------------

class _FakeCore:
    def __init__(self, prefix, workspace_root, env_path, network_name="costaff_default"):
        self.prefix = prefix
        self.workspace_root = workspace_root
        self.env_path = env_path
        self.network_name = network_name


def _make_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "costaff.channel.json").write_text('{"a2a_service": "web", "port": 80}')
    (src / "docker-compose.yaml").write_text(yaml.safe_dump({
        "services": {
            "web": {"build": ".", "ports": ["80:80"]},
            "worker": {"build": "."},
        }
    }))
    return src


def _read_fragment(plugin_env_path):
    frag = os.path.join(os.path.dirname(plugin_env_path), "compose-fragment.yaml")
    with open(frag) as f:
        return yaml.safe_load(f)


def test_fragment_default_core_is_historical_layout(tmp_path, monkeypatch):
    # core=None must reproduce the old global-path behaviour exactly.
    ws = tmp_path / "workspace"
    monkeypatch.setattr("utils.compose._workspace_root", str(ws))
    monkeypatch.setattr("utils.compose.PATHS", {"env": str(tmp_path / ".env")})
    src = _make_source(tmp_path)
    plugin_env = tmp_path / "plugin" / ".env"
    plugin_env.parent.mkdir()

    frag_path, services, _ = _write_channel_fragment(
        "telegram", str(src), 18090, str(plugin_env), core=None)
    frag = _read_fragment(str(plugin_env))

    # a2a service → costaff-channel-telegram; sidecar → costaff-channel-telegram-worker
    assert "costaff-channel-telegram" in frag["services"]
    assert "costaff-channel-telegram-worker" in frag["services"]
    assert set(services) == {"costaff-channel-telegram", "costaff-channel-telegram-worker"}


def test_fragment_uses_core_prefix_and_paths(tmp_path):
    ws = tmp_path / "twk-workspace"
    env_path = tmp_path / "twk.env"
    env_path.write_text("X=1\n")
    core = _FakeCore("twk", str(ws), str(env_path), network_name="costaff_twk")
    src = _make_source(tmp_path)
    plugin_env = tmp_path / "plugin" / ".env"
    plugin_env.parent.mkdir()

    _write_channel_fragment("telegram", str(src), 19090, str(plugin_env), core=core)
    frag = _read_fragment(str(plugin_env))

    # Container names carry the core's prefix
    assert "twk-channel-telegram" in frag["services"]
    # The fragment joins the CORE's network, not the hardcoded default
    assert "costaff_twk" in frag["networks"]
    assert "costaff_twk" in frag["services"]["twk-channel-telegram"]["networks"]
    assert "twk-channel-telegram-worker" in frag["services"]
    a2a = frag["services"]["twk-channel-telegram"]
    # Published port bound with the core's allocation
    assert any("19090:80" in p for p in a2a["ports"])
    # env_file points at the CORE's .env (first) + plugin .env (last)
    assert a2a["env_file"] == [str(env_path), str(plugin_env)]
    # Shared bind mount rooted at the core's workspace
    assert any(str(ws) in str(v) for v in a2a["volumes"])


def _make_source_with_network(tmp_path, netname="costaff_default"):
    """A source whose service hardcodes a network — like the real webchat-oss
    compose that pins `webchat` to `costaff_default`."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "costaff.channel.json").write_text('{"a2a_service": "webchat", "port": 80}')
    (src / "docker-compose.yaml").write_text(yaml.safe_dump({
        "services": {
            "webchat": {"build": ".", "ports": ["18088:80"], "networks": [netname]},
        },
        "networks": {netname: {"external": True}},
    }))
    return src


def test_fragment_replaces_source_hardcoded_network_on_secondary_core(tmp_path):
    # Regression: a source pinning the service to costaff_default must NOT leave
    # that reference behind on a non-default core. The fragment only declares the
    # core's own network, so a stale costaff_default => compose rejects the build
    # with "refers to undefined network costaff_default".
    core = _FakeCore("twk", str(tmp_path / "ws"), str(tmp_path / "twk.env"),
                     network_name="costaff_twk")
    src = _make_source_with_network(tmp_path, "costaff_default")
    plugin_env = tmp_path / "plugin" / ".env"
    plugin_env.parent.mkdir()

    _write_channel_fragment("webchat", str(src), 19095, str(plugin_env), core=core)
    frag = _read_fragment(str(plugin_env))

    svc = frag["services"]["twk-channel-webchat"]
    assert svc["networks"] == ["costaff_twk"]  # source's costaff_default replaced
    # every network the service references must be declared at top level
    assert set(svc["networks"]).issubset(set(frag["networks"]))
    assert "costaff_default" not in frag["networks"]


def test_fragment_default_core_keeps_costaff_default(tmp_path, monkeypatch):
    # On the default core the replacement is a no-op: net IS costaff_default.
    monkeypatch.setattr("utils.compose._workspace_root", str(tmp_path / "ws"))
    monkeypatch.setattr("utils.compose.PATHS", {"env": str(tmp_path / ".env")})
    src = _make_source_with_network(tmp_path, "costaff_default")
    plugin_env = tmp_path / "plugin" / ".env"
    plugin_env.parent.mkdir()

    _write_channel_fragment("webchat", str(src), 18088, str(plugin_env), core=None)
    frag = _read_fragment(str(plugin_env))

    svc = frag["services"]["costaff-channel-webchat"]
    assert svc["networks"] == ["costaff_default"]
    assert "costaff_default" in frag["networks"]


# ---------------------------------------------------------------------------
# command-layer plumbing — remove resolves and acts on the target core
# ---------------------------------------------------------------------------

def test_channel_remove_uses_target_core(monkeypatch):
    import cli.commands.channel as ch

    class _Runtime:
        def __init__(self):
            self.removed = []

        def down(self, **k):
            raise AssertionError("no fragment on disk → should force-remove")

        def force_remove_container(self, name):
            self.removed.append(name)

    class _Core:
        name = "twk"
        prefix = "twk"

        def __init__(self):
            self._conf = {"dynamic_channels": {"telegram": {"container_names": ["twk-channel-telegram"]}}}
            self.regened = False

        def core_config(self):
            return self._conf

        def cn(self, s):
            return f"{self.prefix}-{s}"

        def write_config(self, conf):
            self._conf = conf

        def regen_external_agents_env(self):
            self.regened = True

    core = _Core()
    rt = _Runtime()
    monkeypatch.setattr(ch, "_resolve_core", lambda n: core)
    monkeypatch.setattr(ch, "runtime_for", lambda c: rt)
    monkeypatch.setattr(ch.questionary, "confirm",
                        lambda *a, **k: type("C", (), {"ask": lambda self: True})())

    ch.channel_remove(name="telegram", core_name="twk")

    # Container removed on the twk core, config entry gone, env regenerated
    assert rt.removed == ["twk-channel-telegram"]
    assert "telegram" not in core.core_config()["dynamic_channels"]
    assert core.regened
