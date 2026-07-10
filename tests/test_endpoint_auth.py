"""Regression guard: every dashboard endpoint rejects unauthenticated calls.

Auth is wired per-endpoint (`Depends(AuthManager.verify_token)`), not at the
app level, so a new router endpoint that forgets the dependency would be
silently public. This test enumerates every route on the real app and
asserts that — with no session token and no Authorization header — it
returns 401, except for the deliberately-public allowlist.

If you add a genuinely public endpoint, add it to PUBLIC_ROUTES with a
one-line reason. If this test fails on a NEW endpoint, the fix is almost
always to add the verify_token dependency, not to expand the allowlist.
"""
import pytest
from fastapi.testclient import TestClient

from server.app import server
from services.auth import AuthManager

# The OpenAPI schema is the version-agnostic source of truth for registered
# endpoints (route object internals differ across FastAPI versions).
_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


# (method, path) pairs that are public BY DESIGN.
PUBLIC_ROUTES = {
    ("GET", "/"),                    # SPA index (static shell, no data)
    ("GET", "/health"),             # liveness probe
    ("GET", "/api/check-setup"),    # tells the login page whether to show setup
    ("POST", "/api/setup"),         # first-run account creation (guarded by "already exists")
    ("POST", "/api/login"),         # issues the token in the first place
}


def _all_operations():
    """(method, path) for every registered HTTP operation, from OpenAPI."""
    paths = server.openapi().get("paths", {})
    for path, methods in paths.items():
        for method in methods:
            m = method.upper()
            if m in _HTTP_METHODS:
                yield m, path


def _concrete(path: str) -> str:
    """Fill every {param} with a placeholder so the route matches."""
    import re
    return re.sub(r"\{[^}]+\}", "x", path)


def _iter_routes():
    for method, path in sorted(_all_operations()):
        yield method, path, _concrete(path)


def _param_ids():
    return [f"{m} {p}" for m, p, _c in _iter_routes()]


@pytest.fixture(autouse=True)
def _no_session():
    """Ensure no valid session token is cached on the class object."""
    AuthManager._session_token = ""
    AuthManager._token_expires = 0.0
    yield


@pytest.mark.parametrize("method,path,concrete", list(_iter_routes()), ids=_param_ids())
def test_endpoint_requires_auth(method, path, concrete):
    if (method, path) in PUBLIC_ROUTES:
        pytest.skip("public by design")
    client = TestClient(server)
    resp = client.request(method, concrete)
    # 401 is the contract. A 422 (body validation) would mean auth was NOT
    # enforced first — the dependency is missing.
    assert resp.status_code == 401, (
        f"{method} {path} returned {resp.status_code}, expected 401 — "
        f"missing Depends(AuthManager.verify_token)?"
    )


def test_allowlist_entries_all_exist():
    """Guard the guard: every PUBLIC_ROUTES entry must be a real route, so a
    renamed/removed public endpoint can't silently keep a stale exemption."""
    real = set(_all_operations())
    missing = PUBLIC_ROUTES - real
    assert not missing, f"allowlist references non-existent routes: {missing}"
