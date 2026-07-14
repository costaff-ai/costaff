"""The legacy coding_agent_enabled migration must not fabricate a live agent.

The old behaviour injected an ENABLED `costaff-agent-coding` entry whenever a
config carried the legacy flag — with a default a2a_url pointing at a
container that may never have existed on that host. The entry then flowed
into EXTERNAL_AGENTS_CONFIG and the Manager routed coding tasks into a dead
endpoint. Rules now:

- explicit CODING_A2A_URL / CODING_A2A_INTERNAL_URL → real wiring → enabled;
- bare flag with no URL evidence → entry created DISABLED (visible in
  `costaff agent list`, never routed) + a warning;
- a modern `coding` entry already present → no duplicate; stale flag dropped.
"""
import json
import warnings

import pytest

from services.config import ConfigManager


@pytest.fixture(autouse=True)
def _no_env_leak(monkeypatch):
    """Keep the host's .env and process env out of the migration under test."""
    monkeypatch.setattr("services.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("CODING_A2A_URL", raising=False)
    monkeypatch.delenv("CODING_A2A_INTERNAL_URL", raising=False)


def test_bare_flag_migrates_disabled_with_warning():
    conf = {"coding_agent_enabled": True, "external_agents": {}}
    with pytest.warns(UserWarning, match="DISABLED"):
        assert ConfigManager._migrate_coding_agent(conf) is True
    entry = conf["external_agents"]["costaff-agent-coding"]
    assert entry["enabled"] is False
    assert entry["a2a_url"] == "http://costaff-agent-coding:8081"


def test_explicit_url_migrates_enabled(monkeypatch):
    monkeypatch.setenv("CODING_A2A_URL", "http://my-coding:9000")
    conf = {"coding_agent_enabled": True, "external_agents": {}}
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no warning expected on the real-wiring path
        assert ConfigManager._migrate_coding_agent(conf) is True
    entry = conf["external_agents"]["costaff-agent-coding"]
    assert entry["enabled"] is True
    assert entry["a2a_url"] == "http://my-coding:9000"


def test_modern_coding_entry_wins_and_flag_is_dropped():
    conf = {
        "coding_agent_enabled": True,
        "external_agents": {"coding": {"a2a_url": "http://costaff-agent-coding:8082", "enabled": True}},
    }
    assert ConfigManager._migrate_coding_agent(conf) is True
    assert "costaff-agent-coding" not in conf["external_agents"]
    assert "coding_agent_enabled" not in conf


def test_no_flag_no_migration():
    conf = {"external_agents": {}}
    assert ConfigManager._migrate_coding_agent(conf) is False
    assert conf["external_agents"] == {}


def test_already_migrated_untouched():
    entry = {"a2a_url": "http://x:1", "enabled": True}
    conf = {"coding_agent_enabled": True, "external_agents": {"costaff-agent-coding": dict(entry)}}
    assert ConfigManager._migrate_coding_agent(conf) is False
    assert conf["external_agents"]["costaff-agent-coding"] == entry


def test_get_config_persists_disabled_migration(tmp_path):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps({"coding_agent_enabled": True, "external_agents": {}}))
    with pytest.warns(UserWarning, match="DISABLED"):
        conf = ConfigManager.get_config(str(cp))
    assert conf["external_agents"]["costaff-agent-coding"]["enabled"] is False
    saved = json.loads(cp.read_text())
    assert saved["external_agents"]["costaff-agent-coding"]["enabled"] is False
