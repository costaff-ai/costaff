"""Tests for services/preflight.py — `costaff start` env validation."""
import pytest
from dotenv import dotenv_values

import services.preflight as preflight
from services.preflight import (
    DEFAULT_ID_SALT,
    check_env,
    ensure_postgres_password,
    ensure_security_keys,
    ensure_workspace_dir,
)


def _good_env(**overrides):
    env = {
        "COSTAFF_AGENT_MODEL_PROVIDER": "gemini",
        "GOOGLE_API_KEY": "AIzaFakeKey",
        "ADK_SESSION_SERVICE_URI": "postgresql+asyncpg://costaff:pw@postgres:5432/costaff_db",
        "ID_SALT": "a" * 64,
        "MCP_SECRET_KEY": "b" * 64,
        "API_HEADERS_KEY": "c" * 64,
        "COSTAFF_WORKSPACE_DIR": "/home/user/.costaff/workspace",
    }
    env.update(overrides)
    return env


def test_clean_env_has_no_issues():
    assert check_env(_good_env()) == []


def test_missing_google_api_key_is_fatal():
    issues = check_env(_good_env(GOOGLE_API_KEY=""))
    assert any(i.fatal and "GOOGLE_API_KEY" in i.message for i in issues)


def test_provider_defaults_to_gemini_when_unset():
    issues = check_env(_good_env(COSTAFF_AGENT_MODEL_PROVIDER="", GOOGLE_API_KEY=""))
    assert any(i.fatal and "GOOGLE_API_KEY" in i.message for i in issues)


def test_litellm_requires_model_and_base():
    env = _good_env(
        COSTAFF_AGENT_MODEL_PROVIDER="litellm",
        LITELLM_MODEL_NAME="", LITELLM_API_BASE="",
    )
    issues = check_env(env)
    fatal_msgs = [i.message for i in issues if i.fatal]
    assert any("LITELLM_MODEL_NAME" in m for m in fatal_msgs)
    assert any("LITELLM_API_BASE" in m for m in fatal_msgs)


def test_litellm_complete_passes_without_google_key():
    env = _good_env(
        COSTAFF_AGENT_MODEL_PROVIDER="litellm",
        GOOGLE_API_KEY="",
        LITELLM_MODEL_NAME="ollama/llama3",
        LITELLM_API_BASE="http://host.docker.internal:11434",
    )
    assert check_env(env) == []


def test_unknown_provider_is_fatal():
    issues = check_env(_good_env(COSTAFF_AGENT_MODEL_PROVIDER="banana"))
    assert any(i.fatal and "banana" in i.message for i in issues)


def test_missing_db_uri_is_fatal():
    issues = check_env(_good_env(ADK_SESSION_SERVICE_URI=""))
    assert any(i.fatal and "ADK_SESSION_SERVICE_URI" in i.message for i in issues)


def test_template_id_salt_warns_but_not_fatal():
    issues = check_env(_good_env(ID_SALT=DEFAULT_ID_SALT))
    salt_issues = [i for i in issues if "ID_SALT" in i.message]
    assert salt_issues and not salt_issues[0].fatal


def test_missing_secrets_warn_but_not_fatal():
    issues = check_env(_good_env(MCP_SECRET_KEY="", API_HEADERS_KEY=""))
    msgs = [i.message for i in issues]
    assert any("MCP_SECRET_KEY" in m for m in msgs)
    assert any("API_HEADERS_KEY" in m for m in msgs)
    assert all(not i.fatal for i in issues)


def test_quoted_values_are_unwrapped():
    issues = check_env(_good_env(GOOGLE_API_KEY="'AIzaFakeKey'"))
    assert not any("GOOGLE_API_KEY" in i.message for i in issues)


def test_ensure_security_keys_generates_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"ID_SALT={DEFAULT_ID_SALT}\nMCP_SECRET_KEY=\n")
    generated = ensure_security_keys(str(env_file))
    assert set(generated) == {"MCP_SECRET_KEY", "API_HEADERS_KEY", "ID_SALT"}
    values = dotenv_values(env_file)
    assert values["ID_SALT"] != DEFAULT_ID_SALT
    assert len(values["MCP_SECRET_KEY"]) == 64
    # API_HEADERS_KEY must be a *valid Fernet key* (urlsafe-base64 32 bytes),
    # not token_hex(32) — the latter silently disabled header encryption.
    from cryptography.fernet import Fernet
    Fernet(values["API_HEADERS_KEY"].encode())  # raises if not a valid key


def test_ensure_security_keys_idempotent(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    first = ensure_security_keys(str(env_file))
    assert len(first) == 3
    before = dotenv_values(env_file)
    assert ensure_security_keys(str(env_file)) == []
    assert dotenv_values(env_file) == before


def test_missing_workspace_dir_is_fatal():
    # docker-compose.yaml hard-requires COSTAFF_WORKSPACE_DIR (`${…:?}`), so
    # preflight must block start instead of warn-and-crash-later.
    issues = check_env(_good_env(COSTAFF_WORKSPACE_DIR=""))
    assert any(i.fatal and "COSTAFF_WORKSPACE_DIR" in i.message for i in issues)


def test_ensure_workspace_dir_writes_and_creates(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    ws = tmp_path / "workspace"
    monkeypatch.setattr(preflight, "_workspace_root", str(ws))
    assert ensure_workspace_dir(str(env_file)) is True
    assert (ws / "shared").is_dir()
    assert dotenv_values(env_file)["COSTAFF_WORKSPACE_DIR"] == str(ws)
    # Idempotent: an existing value is never overwritten
    assert ensure_workspace_dir(str(env_file)) is False


def _pg_env(tmp_path, uri_line=True):
    env_file = tmp_path / ".env"
    lines = ["POSTGRES_USER=costaff", "POSTGRES_PASSWORD=costaff_pass"]
    if uri_line:
        lines.append(
            "ADK_SESSION_SERVICE_URI="
            "postgresql+asyncpg://costaff:${POSTGRES_PASSWORD}@postgres:5432/costaff_db"
        )
    env_file.write_text("\n".join(lines) + "\n")
    return env_file


def test_postgres_password_rotated_on_fresh_install(tmp_path, monkeypatch):
    env_file = _pg_env(tmp_path)
    monkeypatch.setattr(preflight, "_postgres_volume_exists", lambda: False)
    assert ensure_postgres_password(str(env_file)) is True
    values = dotenv_values(env_file)
    assert values["POSTGRES_PASSWORD"] != "costaff_pass"
    # The template URI interpolates ${POSTGRES_PASSWORD} → follows the rotation
    assert values["POSTGRES_PASSWORD"] in values["ADK_SESSION_SERVICE_URI"]
    # Idempotent: second run sees a non-default password and leaves it alone
    assert ensure_postgres_password(str(env_file)) is False


def test_postgres_password_kept_when_volume_exists(tmp_path, monkeypatch):
    # An initialized volume keeps its original password — rotating .env
    # would lock the stack out of its own DB.
    env_file = _pg_env(tmp_path)
    monkeypatch.setattr(preflight, "_postgres_volume_exists", lambda: True)
    assert ensure_postgres_password(str(env_file)) is False
    assert dotenv_values(env_file)["POSTGRES_PASSWORD"] == "costaff_pass"


def test_postgres_password_kept_when_docker_unreachable(tmp_path, monkeypatch):
    env_file = _pg_env(tmp_path)
    monkeypatch.setattr(preflight, "_postgres_volume_exists", lambda: None)
    assert ensure_postgres_password(str(env_file)) is False


def test_postgres_password_kept_with_custom_uri(tmp_path, monkeypatch):
    # A URI pointing at an external DB (no default credentials) must never
    # be broken by a rotation of the bundled-postgres password.
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=costaff_pass\n"
        "ADK_SESSION_SERVICE_URI=postgresql+asyncpg://me:secret@db.example.com:5432/prod\n"
    )
    monkeypatch.setattr(preflight, "_postgres_volume_exists", lambda: False)
    assert ensure_postgres_password(str(env_file)) is False
