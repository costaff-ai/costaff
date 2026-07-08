"""Multi-core CLI plumbing: CoreContext derived paths, --core resolution,
cross-core port reservation, and core-scoped compose runtime."""
import json

import pytest
from unittest.mock import patch

from services.cores import CoreContext, get_core, all_used_public_ports
from services.runtime import runtime_for
from services.runtime.docker import DockerRuntime
from utils.ports import _next_available_port


TWK = {
    "label": "Twinkle",
    "container_prefix": "twk",
    "manager_port": 19085,
    "config_path": "/Users/x/costaff-demo/twk/.costaff/costaff/config.json",
    "env_path": "/Users/x/costaff-demo/twk/.costaff/costaff/.env",
    "compose_file": "/Users/x/costaff-demo/twk/.costaff/costaff/docker-compose.yaml",
    "compose_project": "twk-core",
}


def test_core_context_derived_paths():
    core = CoreContext("twk", TWK)
    assert core.runtime_root == "/Users/x/costaff-demo/twk/.costaff/costaff"
    assert core.base_dir == "/Users/x/costaff-demo/twk/.costaff"
    assert core.workspace_root == "/Users/x/costaff-demo/twk/.costaff/workspace"
    assert core.main_compose == TWK["compose_file"]
    assert not core.is_default
    assert core.cn("agent-costaff") == "twk-agent-costaff"


def test_default_core_layout_matches_single_install():
    from utils.paths import PATHS, _runtime_root, _base_dir, _workspace_root

    core = CoreContext("default", {})
    assert core.is_default
    assert core.config_path == PATHS["config"]
    assert core.runtime_root == _runtime_root
    assert core.base_dir == _base_dir
    assert core.workspace_root == _workspace_root
    assert core.prefix == "costaff"


def test_get_core_resolution(monkeypatch):
    registry = ({"twk": TWK, "asst": dict(TWK, container_prefix="asst")}, "asst")
    monkeypatch.setattr("services.cores._registry", lambda: registry)
    assert get_core(None).name == "asst"          # active core default
    assert get_core("twk").name == "twk"          # explicit --core
    with pytest.raises(ValueError, match="unknown core"):
        get_core("nope")


def test_all_used_public_ports_spans_cores(tmp_path, monkeypatch):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"external_agents": {"x": {"public_port": 18110}}}))
    b.write_text(json.dumps({"external_agents": {"y": {"public_port": 18111}},
                             "dynamic_channels": {"c": {"public_port": 18090}}}))
    registry = ({
        "one": {"config_path": str(a)},
        "two": {"config_path": str(b)},
    }, "one")
    monkeypatch.setattr("services.cores._registry", lambda: registry)
    assert all_used_public_ports() == {18110, 18111, 18090}


def test_next_available_port_respects_reserved():
    conf = {"external_agents": {"x": {"public_port": 18100}}}
    assert _next_available_port(conf) == 18101
    assert _next_available_port(conf, reserved={18101, 18102}) == 18103


def test_docker_runtime_project_flag(tmp_path):
    rt = DockerRuntime(compose_cwd=str(tmp_path), base_compose="/c/compose.yaml", project="twk-core")
    assert rt._compose_args("/f/frag.yaml") == [
        "-p", "twk-core", "-f", "/c/compose.yaml", "-f", "/f/frag.yaml",
    ]
    # without a project, no -p is injected (legacy single-install behaviour)
    rt2 = DockerRuntime(compose_cwd=str(tmp_path), base_compose="compose.yaml")
    assert rt2._compose_args() == ["-f", "compose.yaml"]


def test_runtime_for_binds_core_compose():
    rt = runtime_for(CoreContext("twk", TWK))
    assert isinstance(rt, DockerRuntime)
    assert rt.base_compose == TWK["compose_file"]
    assert rt.project == "twk-core"
    assert rt.compose_cwd == "/Users/x/costaff-demo/twk/.costaff/costaff"


def test_runtime_for_default_core_uses_get_runtime():
    with patch("services.runtime.get_runtime") as gr:
        gr.return_value = "sentinel"
        assert runtime_for(CoreContext("default", {})) == "sentinel"
