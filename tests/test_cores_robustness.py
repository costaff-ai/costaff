"""Robustness fixes for services.cores and services.runtime.docker."""
import subprocess

import pytest

import services.cores as cores
from services.runtime.docker import DockerRuntime


# ---------------------------------------------------------------------------
# all_used_public_ports must not crash when ANOTHER core's config is corrupt
# ---------------------------------------------------------------------------

def test_all_used_public_ports_skips_corrupt_core(monkeypatch):
    good = {"container_prefix": "good", "config_path": "/x/good/config.json"}
    bad = {"container_prefix": "bad", "config_path": "/x/bad/config.json"}
    monkeypatch.setattr(cores, "_registry", lambda: ({"good": good, "bad": bad}, "good"))

    def fake_core_config(self):
        if self.name == "bad":
            raise RuntimeError("config.json is unreadable")
        return {"external_agents": {"a": {"public_port": 18110}},
                "dynamic_channels": {"c": {"public_port": 18090}}}

    monkeypatch.setattr(cores.CoreContext, "core_config", fake_core_config)

    with pytest.warns(UserWarning):
        used = cores.all_used_public_ports()
    # good core's ports still counted; bad core skipped, not fatal
    assert used == {18110, 18090}


# ---------------------------------------------------------------------------
# set_active validates even on single-install (no `cores` key)
# ---------------------------------------------------------------------------

def test_set_active_rejects_unknown_on_single_install(monkeypatch):
    monkeypatch.setattr(cores.ConfigManager, "get_config", staticmethod(lambda: {}))
    saved = {}
    monkeypatch.setattr(cores.ConfigManager, "save_config", staticmethod(lambda c, *a: saved.update(c)))

    with pytest.raises(ValueError):
        cores.set_active("nonexistent")
    assert saved == {}  # nothing written


def test_set_active_accepts_default_on_single_install(monkeypatch):
    monkeypatch.setattr(cores.ConfigManager, "get_config", staticmethod(lambda: {}))
    saved = {}
    monkeypatch.setattr(cores.ConfigManager, "save_config", staticmethod(lambda c, *a: saved.update(c)))

    assert cores.set_active("default") == "default"
    assert saved["active_core"] == "default"


# ---------------------------------------------------------------------------
# recreate_manager returns a bool
# ---------------------------------------------------------------------------

def test_recreate_manager_returns_bool_on_compose_core(monkeypatch):
    core = cores.CoreContext("twk", {
        "container_prefix": "twk", "config_path": "/x/twk/config.json",
        "compose_project": "twk-core", "compose_file": "/x/twk/docker-compose.yaml",
    })

    class _R:
        returncode = 0
    monkeypatch.setattr(cores.subprocess, "run", lambda *a, **k: _R())
    assert core.recreate_manager() is True

    class _F:
        returncode = 1
    monkeypatch.setattr(cores.subprocess, "run", lambda *a, **k: _F())
    assert core.recreate_manager() is False


# ---------------------------------------------------------------------------
# runtime.up raises RuntimeError (not CalledProcessError) on failure
# ---------------------------------------------------------------------------

def test_network_name_read_from_base_compose(tmp_path):
    compose = tmp_path / "docker-compose.yaml"
    compose.write_text(
        "services: {}\nnetworks:\n  default:\n    name: costaff_twk\n    external: true\n"
    )
    core = cores.CoreContext("twk", {
        "container_prefix": "twk",
        "config_path": str(tmp_path / "config.json"),
        "compose_file": str(compose),
    })
    assert core.network_name == "costaff_twk"


def test_network_name_falls_back_to_default(tmp_path):
    # No compose / no networks section → costaff_default (single-install net)
    core = cores.CoreContext("default", {
        "config_path": str(tmp_path / "config.json"),
    })
    assert core.network_name == "costaff_default"


def test_runtime_up_raises_runtimeerror(monkeypatch):
    rt = DockerRuntime(base_compose="/x/docker-compose.yaml", project="", compose_cwd="/x")

    class _Fail:
        returncode = 1
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Fail())
    with pytest.raises(RuntimeError):
        rt.up(["svc"])
