"""Tests for `costaff agent model` write-target resolution.

Regression for the GA-audit no-op bug: for EXTERNAL agents the command
printed a green success but wrote nothing — the config entry never carried
model_env_var/provider_env_var, and even when it did, the write went to the
core .env which the plugin .env (last in env_file order) overrides.

Contract:
- External agents write to the PLUGIN .env next to their compose fragment.
- Entries without model_env_var recover it from the manifest on disk.
- url-type agents (no fragment) are skipped and the command exits non-zero
  when nothing was written.
- Values are written WITHOUT quotes (docker compose env_file parses
  single-quoted values literally).
"""
import json

import pytest
import typer

from cli.commands import agent_model as mod


def _entry_with_fragment(tmp_path, **extra):
    frag_dir = tmp_path / "costaff-agent" / "coding"
    frag_dir.mkdir(parents=True)
    (frag_dir / "compose-fragment.yaml").write_text("services: {}\n")
    entry = {
        "type": "github",
        "fragment_path": str(frag_dir / "compose-fragment.yaml"),
        "a2a_url": "http://costaff-agent-coding:8081",
        **extra,
    }
    return entry, frag_dir / ".env"


def test_external_target_uses_plugin_env_and_declared_var(tmp_path):
    entry, plugin_env = _entry_with_fragment(
        tmp_path, model_env_var="CODING_AGENT_MODEL",
        provider_env_var="COSTAFF_AGENT_MODEL_PROVIDER",
    )
    t = mod._external_target("coding", entry)
    assert t["env_path"] == str(plugin_env)
    assert t["model_env_var"] == "CODING_AGENT_MODEL"
    assert t["provider_env_var"] == "COSTAFF_AGENT_MODEL_PROVIDER"


def test_legacy_entry_recovers_model_var_from_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "costaff.agent.json").write_text(json.dumps({
        "name": "costaff-agent-coding",
        "model_env_var": "CODING_AGENT_MODEL",
    }))
    entry, plugin_env = _entry_with_fragment(tmp_path, source_path=str(src))
    t = mod._external_target("coding", entry)
    assert t["model_env_var"] == "CODING_AGENT_MODEL"
    assert t["provider_env_var"] == "COSTAFF_AGENT_MODEL_PROVIDER"
    assert t["env_path"] == str(plugin_env)


def test_url_type_agent_has_no_write_surface():
    t = mod._external_target("remote", {"type": "url", "a2a_url": "http://x:8081"})
    assert t["env_path"] == ""
    assert t["model_env_var"] == ""


def test_write_env_key_is_unquoted(tmp_path):
    env = tmp_path / ".env"
    env.write_text("CODING_AGENT_MODEL='old'\nOTHER=1\n")
    mod._write_env_key(str(env), "CODING_AGENT_MODEL", "gemini-3-pro")
    mod._write_env_key(str(env), "NEW_KEY", "value")
    content = env.read_text()
    assert "CODING_AGENT_MODEL=gemini-3-pro\n" in content
    assert "NEW_KEY=value\n" in content
    assert "'" not in content.replace("'old'", "")  # no quotes introduced


def _run_agent_model(monkeypatch, tmp_path, agents, name, **kwargs):
    """Invoke the command function with a fake core context."""
    core_env = tmp_path / "core.env"
    core_env.touch()

    class FakeCore:
        env_path = str(core_env)

        def core_config(self):
            return {"external_agents": agents}

    monkeypatch.setattr(mod, "_resolve_core", lambda _n: FakeCore())
    mod.agent_model(
        name=name,
        provider=kwargs.get("provider", "gemini"),
        model=kwargs.get("model", "gemini-3-pro"),
        api_base=None, api_key=None, show=False, core_name=None,
    )
    return core_env


def test_external_agent_write_goes_to_plugin_env(tmp_path, monkeypatch):
    entry, plugin_env = _entry_with_fragment(
        tmp_path, model_env_var="CODING_AGENT_MODEL",
        provider_env_var="COSTAFF_AGENT_MODEL_PROVIDER",
    )
    core_env = _run_agent_model(monkeypatch, tmp_path, {"coding": entry}, "coding")

    written = plugin_env.read_text()
    assert "CODING_AGENT_MODEL=gemini-3-pro\n" in written
    assert "COSTAFF_AGENT_MODEL_PROVIDER=gemini\n" in written
    # The core .env must be untouched — plugin .env wins in env_file order,
    # and the provider key in core .env is the manager's global setting.
    assert core_env.read_text() == ""


def test_url_agent_exits_nonzero_instead_of_fake_success(tmp_path, monkeypatch):
    agents = {"remote": {"type": "url", "a2a_url": "http://x:8081"}}
    with pytest.raises(typer.Exit) as exc:
        _run_agent_model(monkeypatch, tmp_path, agents, "remote")
    assert exc.value.exit_code == 1


def test_core_agent_writes_core_env(tmp_path, monkeypatch):
    core_env = _run_agent_model(
        monkeypatch, tmp_path, {}, "costaff-agent-costaff",
    )
    content = core_env.read_text()
    assert "COSTAFF_AGENT_GEMINI_MODEL=gemini-3-pro\n" in content
    assert "COSTAFF_AGENT_MODEL_PROVIDER=gemini\n" in content
