"""`_ensure_webchat_push_env` auto-wires async "notify you later" for WebChat.

Host-side, docker-free. Writing WEBCHAT_PUSH_URL + WEBCHAT_INTERNAL_SECRET to
the core .env is all it takes for the core's notifier (sender) and the webchat
container (which mounts that .env as an env_file) to agree on the
/api/internal/push handshake — so the user does zero manual setup.
"""
from dotenv import dotenv_values

from cli.commands.channel import _ensure_webchat_push_env


class _FakeCore:
    def __init__(self, env_path, prefix="costaff"):
        self.env_path = str(env_path)
        self.prefix = prefix

    def cn(self, suffix):
        return f"{self.prefix}-{suffix}"


def test_webchat_channel_gets_push_url_and_secret(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXISTING=1\n")
    _ensure_webchat_push_env(_FakeCore(env), "webchat")

    vals = dotenv_values(str(env))
    assert vals["WEBCHAT_PUSH_URL"] == "http://costaff-channel-webchat:80/api/internal/push"
    assert len(vals["WEBCHAT_INTERNAL_SECRET"]) >= 20  # generated, non-trivial
    assert vals["EXISTING"] == "1"  # unrelated keys untouched


def test_existing_secret_is_preserved(tmp_path):
    # A rebuild/restart must NOT rotate the secret — the running webchat
    # container is already validating against the old value.
    env = tmp_path / ".env"
    env.write_text("WEBCHAT_INTERNAL_SECRET=keepme\n")
    _ensure_webchat_push_env(_FakeCore(env), "webchat")

    vals = dotenv_values(str(env))
    assert vals["WEBCHAT_INTERNAL_SECRET"] == "keepme"
    assert vals["WEBCHAT_PUSH_URL"].endswith("/api/internal/push")


def test_push_url_uses_core_container_prefix(tmp_path):
    # Multi-core: the URL must target THIS core's webchat container.
    env = tmp_path / ".env"
    env.write_text("")
    _ensure_webchat_push_env(_FakeCore(env, prefix="twk"), "webchat")

    vals = dotenv_values(str(env))
    assert vals["WEBCHAT_PUSH_URL"] == "http://twk-channel-webchat:80/api/internal/push"


def test_non_webchat_channel_is_skipped(tmp_path):
    # Telegram/Discord/etc. have no /api/internal/push receiver — don't touch .env.
    env = tmp_path / ".env"
    env.write_text("EXISTING=1\n")
    _ensure_webchat_push_env(_FakeCore(env), "telegram")

    vals = dotenv_values(str(env))
    assert "WEBCHAT_PUSH_URL" not in vals
    assert "WEBCHAT_INTERNAL_SECRET" not in vals
