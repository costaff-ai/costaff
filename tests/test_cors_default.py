"""The dashboard must not ship a wildcard CORS policy.

The frontend is served same-origin by the same app, so no CORS is needed
by default. Regression for the audit finding that ALLOWED_ORIGINS
defaulted to "*", letting any website script the dashboard.
"""
import importlib

from fastapi.testclient import TestClient


def _fresh_app(monkeypatch, origins_env):
    """Reimport server.app with ALLOWED_ORIGINS set to `origins_env`."""
    if origins_env is None:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_ORIGINS", origins_env)
    import server.app as app_mod
    return importlib.reload(app_mod).server


def test_default_has_no_wildcard_cors(monkeypatch):
    server = _fresh_app(monkeypatch, None)
    client = TestClient(server)
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    acao = r.headers.get("access-control-allow-origin")
    assert acao != "*"
    assert acao != "https://evil.example"


def test_configured_origin_is_allowed(monkeypatch):
    server = _fresh_app(monkeypatch, "https://ops.example")
    client = TestClient(server)
    r = client.get("/health", headers={"Origin": "https://ops.example"})
    assert r.headers.get("access-control-allow-origin") == "https://ops.example"


def test_configured_origin_does_not_allow_others(monkeypatch):
    server = _fresh_app(monkeypatch, "https://ops.example")
    client = TestClient(server)
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"


def test_cleanup_reload(monkeypatch):
    """Leave server.app reimported with a clean env so other test modules
    (which import the shared `server`) see the default configuration."""
    _fresh_app(monkeypatch, None)
