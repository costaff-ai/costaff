"""Tests for services/preflight.py — `costaff start` env validation."""
import pytest
from dotenv import dotenv_values

from services.preflight import DEFAULT_ID_SALT, check_env, ensure_security_keys


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
