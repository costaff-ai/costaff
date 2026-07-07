"""App-Store-style platform registration (remote URL-only platforms)."""
import json

import pytest
from fastapi.testclient import TestClient

import services.config as config_mod
from server.app import server
from services.auth import AuthManager
from services.platform_registry import OFFICIAL_PLATFORMS


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    # `channels` must be present: get_config migrates a legacy top-level
    # "platforms" key into "channels" when channels is missing.
    cfg.write_text(json.dumps({
        "channels": [],
        "platforms": {
            "erp": {"source_path": "/opt/erp", "public_port": 18210, "enabled": True},
        },
    }))
    monkeypatch.setitem(config_mod.PATHS, "config", str(cfg))
    import server.routers.platforms as plat_mod
    monkeypatch.setattr(plat_mod, "_probe", lambda url: "down")
    server.dependency_overrides[AuthManager.verify_token] = lambda: True
    yield TestClient(server)
    server.dependency_overrides.pop(AuthManager.verify_token, None)


def _platforms(cfg_path):
    return json.loads(open(cfg_path).read())["platforms"]


def test_registry_entries_are_complete():
    for name, meta in OFFICIAL_PLATFORMS.items():
        assert {"github", "prefix", "oidc", "port", "description", "icon"} <= set(meta), name


def test_catalog_excludes_db_and_flags_registered(client):
    apps = {a["name"]: a for a in client.get("/api/platforms/catalog").json()}
    assert "db" not in apps                      # infra w/o frontend isn't storefront material
    assert apps["erp"]["registered"] is True
    assert apps["crm"]["registered"] is False
    assert apps["crm"]["icon"] and apps["crm"]["description"]


def test_register_remote_platform(client, tmp_path):
    r = client.post("/api/platforms", json={
        "name": "crm", "url": "http://192.168.1.10:18250/",
        "mcp_url": "http://192.168.1.10:18251/mcp", "description": "office CRM",
    })
    assert r.status_code == 200
    entry = _platforms(tmp_path / "config.json")["crm"]
    assert entry["type"] == "remote"
    assert entry["url"] == "http://192.168.1.10:18250"   # trailing slash stripped
    assert entry["mcp_url"] == "http://192.168.1.10:18251/mcp"

    listed = {p["name"]: p for p in client.get("/api/platforms").json()}
    assert listed["crm"]["type"] == "remote"
    assert listed["crm"]["url"] == "http://192.168.1.10:18250"
    assert listed["erp"]["type"] == "local"


def test_register_rejects_dup_and_bad_input(client):
    assert client.post("/api/platforms", json={"name": "erp", "url": "http://x:1"}).status_code == 409
    assert client.post("/api/platforms", json={"name": "Bad Name!", "url": "http://x:1"}).status_code == 400
    assert client.post("/api/platforms", json={"name": "ok", "url": "ftp://x:1"}).status_code == 400


def test_update_and_remove_remote_only(client, tmp_path):
    client.post("/api/platforms", json={"name": "kb", "url": "http://a:1"})

    r = client.put("/api/platforms/kb", json={"url": "https://kb.example.com", "enabled": False})
    assert r.status_code == 200
    entry = _platforms(tmp_path / "config.json")["kb"]
    assert entry["url"] == "https://kb.example.com"
    assert entry["enabled"] is False

    # local platforms stay CLI-managed
    assert client.put("/api/platforms/erp", json={"url": "http://x:1"}).status_code == 400
    assert client.delete("/api/platforms/erp").status_code == 400

    assert client.delete("/api/platforms/kb").status_code == 200
    assert "kb" not in _platforms(tmp_path / "config.json")
    assert client.delete("/api/platforms/kb").status_code == 404


def test_action_rejected_for_remote(client):
    client.post("/api/platforms", json={"name": "kb", "url": "http://a:1"})
    r = client.post("/api/platforms/kb/action", json={"action": "start"})
    assert r.status_code == 400
    assert "remote" in r.json()["detail"]
