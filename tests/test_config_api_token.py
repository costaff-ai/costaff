"""GET /api/config must not return bot tokens in plaintext.

It reports only `token_set` (bool). The gateway form renders an empty
field; save_gateway preserves the existing token when the field is blank.
"""
import pytest
from fastapi.testclient import TestClient

import server.routers.config as config_mod
from server.app import server
from services.auth import AuthManager


@pytest.fixture
def client(monkeypatch):
    # Bypass auth for the endpoint call.
    server.dependency_overrides[AuthManager.verify_token] = lambda: True

    class _Core:
        def core_config(self):
            return {"gateways_config": {}}
    monkeypatch.setattr(config_mod, "active_core", lambda: _Core())
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: None)
    yield TestClient(server)
    server.dependency_overrides.clear()


def test_config_reports_token_set_not_plaintext(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-tg-token-123")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.text
    # The raw token must never appear in the response
    assert "secret-tg-token-123" not in body

    gw = resp.json()["gateways_config"]
    assert gw["tg"]["token_set"] is True
    assert gw["dc"]["token_set"] is False
    # And there is no plaintext `token` key
    assert "token" not in gw["tg"]
