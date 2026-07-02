"""Pre-start environment validation and first-run auto-repair.

`check_env()` inspects `.env` and returns a list of `Issue`s, each with a
human-readable problem and a concrete fix. `costaff start` runs it before
touching Docker so a first-time user gets "GOOGLE_API_KEY is not set →
run `costaff onboard`" instead of a container crash-loop.

`ensure_security_keys()` generates the random secrets every install needs
(MCP_SECRET_KEY / API_HEADERS_KEY / ID_SALT) when they're missing — shared
by `costaff onboard` (interactive) and `costaff bootstrap` (CI).
"""
import os
import secrets as _secrets
from dataclasses import dataclass

from dotenv import dotenv_values, set_key

from utils.paths import PATHS

DEFAULT_ID_SALT = "change-me-to-a-random-string"


@dataclass
class Issue:
    message: str
    fix: str
    fatal: bool = False


def _val(env: dict, key: str) -> str:
    return (env.get(key) or "").strip().strip("'\"")


def check_env(env: dict | None = None) -> list[Issue]:
    """Validate the core `.env` for the values containers need at boot.

    Pass `env` explicitly for testing; defaults to reading PATHS["env"].
    """
    if env is None:
        if not os.path.exists(PATHS["env"]):
            return [Issue(
                f".env not found at {PATHS['env']}",
                "Run `costaff onboard` to create it interactively.",
                fatal=True,
            )]
        env = dotenv_values(PATHS["env"])

    issues: list[Issue] = []

    provider = _val(env, "COSTAFF_AGENT_MODEL_PROVIDER") or "gemini"
    if provider == "gemini":
        if not _val(env, "GOOGLE_API_KEY"):
            issues.append(Issue(
                "GOOGLE_API_KEY is not set (model provider is 'gemini')",
                "Get a free key at https://aistudio.google.com/apikey, "
                "then run `costaff onboard` to store it.",
                fatal=True,
            ))
    elif provider == "litellm":
        if not _val(env, "LITELLM_MODEL_NAME"):
            issues.append(Issue(
                "LITELLM_MODEL_NAME is not set (model provider is 'litellm')",
                "Run `costaff onboard` and pick LiteLLM, or set it in "
                f"{PATHS['env']} (e.g. ollama/llama3).",
                fatal=True,
            ))
        if not _val(env, "LITELLM_API_BASE"):
            issues.append(Issue(
                "LITELLM_API_BASE is not set (model provider is 'litellm')",
                "Set the OpenAI-compatible base URL, e.g. "
                "http://host.docker.internal:11434 for a local Ollama.",
                fatal=True,
            ))
    else:
        issues.append(Issue(
            f"Unknown COSTAFF_AGENT_MODEL_PROVIDER '{provider}'",
            "Set it to 'gemini' or 'litellm' (run `costaff onboard`).",
            fatal=True,
        ))

    if not _val(env, "ADK_SESSION_SERVICE_URI"):
        issues.append(Issue(
            "ADK_SESSION_SERVICE_URI is not set (PostgreSQL connection string)",
            "Run `costaff onboard` — the default "
            "postgresql+asyncpg://costaff:costaff_pass@postgres:5432/costaff_db "
            "works with the bundled Postgres container.",
            fatal=True,
        ))

    if _val(env, "ID_SALT") in ("", DEFAULT_ID_SALT):
        issues.append(Issue(
            "ID_SALT is still the template placeholder",
            "Run `costaff onboard` to generate a random salt "
            "(changing it later breaks existing identity hashes).",
        ))

    for key in ("MCP_SECRET_KEY", "API_HEADERS_KEY"):
        if not _val(env, key):
            issues.append(Issue(
                f"{key} is empty — internal APIs would run unauthenticated",
                "Run `costaff onboard` to generate it.",
            ))

    if not _val(env, "COSTAFF_WORKSPACE_DIR"):
        issues.append(Issue(
            "COSTAFF_WORKSPACE_DIR is not set",
            "The shared /app/data bind mount falls back to an anonymous "
            "volume. Add COSTAFF_WORKSPACE_DIR=$HOME/.costaff/workspace "
            f"to {PATHS['env']} (install.sh writes this automatically).",
        ))

    return issues


def ensure_security_keys(env_path: str | None = None) -> list[str]:
    """Generate MCP_SECRET_KEY / API_HEADERS_KEY / ID_SALT when missing.

    Returns the list of keys that were (re)generated.
    """
    env_path = env_path or PATHS["env"]
    existing = dotenv_values(env_path) if os.path.exists(env_path) else {}
    generated: list[str] = []

    from cryptography.fernet import Fernet

    for key in ("MCP_SECRET_KEY", "API_HEADERS_KEY"):
        if not _val(existing, key):
            # API_HEADERS_KEY encrypts integration headers via Fernet, which
            # requires a urlsafe-base64 32-byte key — token_hex(32) is NOT one
            # and silently disabled encryption (plaintext storage). See
            # utils/crypto.py. MCP_SECRET_KEY is an opaque bearer secret.
            value = (Fernet.generate_key().decode() if key == "API_HEADERS_KEY"
                     else _secrets.token_hex(32))
            set_key(env_path, key, value)
            generated.append(key)

    if _val(existing, "ID_SALT") in ("", DEFAULT_ID_SALT):
        set_key(env_path, "ID_SALT", _secrets.token_hex(32))
        generated.append("ID_SALT")

    return generated
