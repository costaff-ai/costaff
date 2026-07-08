"""CRUD ownership on external agents: whoever added a resource owns its deletion.

- UI-added url agents (added_by == "ui")   → UI-deletable.
- CLI-added url agents (added_by == "cli") → dashboard DELETE rejects (CLI only).
- github/local container deploys           → dashboard DELETE rejects (CLI only).
- legacy unstamped url entries             → still UI-deletable (grandfathered).
"""
import pytest
from fastapi.testclient import TestClient

import server.routers.agents as agents_mod
from server.app import server
from services.auth import AuthManager


class _FakeCore:
    name = "test-core"

    def __init__(self, conf):
        self._conf = conf

    def core_config(self):
        return self._conf

    def write_config(self, conf):
        self._conf = conf

    def regen_external_agents_env(self):
        pass

    def recreate_manager(self):
        pass


@pytest.fixture
def client(monkeypatch):
    core = _FakeCore({
        "external_agents": {
            "ui-agent":     {"type": "url", "added_by": "ui", "a2a_url": "http://a:1", "enabled": True},
            "cli-agent":    {"type": "url", "added_by": "cli", "a2a_url": "http://b:1", "enabled": True},
            "legacy-agent": {"type": "url", "a2a_url": "http://c:1", "enabled": True},
            "deployed":     {"type": "github", "a2a_url": "http://d:1", "public_port": 18110, "enabled": True},
        },
    })
    monkeypatch.setattr(agents_mod, "active_core", lambda: core)
    server.dependency_overrides[AuthManager.verify_token] = lambda: True
    yield TestClient(server), core
    server.dependency_overrides.pop(AuthManager.verify_token, None)


def test_ui_added_is_ui_deletable(client):
    c, core = client
    assert c.delete("/api/external-agents/ui-agent").status_code == 200
    assert "ui-agent" not in core.core_config()["external_agents"]


def test_cli_added_is_rejected_with_cli_pointer(client):
    c, core = client
    r = c.delete("/api/external-agents/cli-agent")
    assert r.status_code == 400
    assert "costaff agent remove" in r.json()["detail"]
    assert "cli-agent" in core.core_config()["external_agents"]


def test_github_deploy_is_rejected(client):
    c, core = client
    r = c.delete("/api/external-agents/deployed")
    assert r.status_code == 400
    assert "deployed" in core.core_config()["external_agents"]


def test_legacy_unstamped_stays_ui_deletable(client):
    c, core = client
    assert c.delete("/api/external-agents/legacy-agent").status_code == 200
    assert "legacy-agent" not in core.core_config()["external_agents"]


def test_ui_add_stamps_added_by(client):
    c, core = client
    r = c.post("/api/external-agents", json={"name": "new-one", "a2a_url": "http://e:8080"})
    assert r.status_code == 200
    assert core.core_config()["external_agents"]["new-one"]["added_by"] == "ui"
