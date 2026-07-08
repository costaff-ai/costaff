"""Interactive plugin .env management for `costaff agent add` / `channel add`.

Reads the agent/channel manifest, prompts the user for required and optional
env vars (skipping anything already provided in `predefined_envs`), and writes
the result to the plugin's compose-fragment .env file.

Also writes required vars back to the core .env so docker-compose YAML
variable substitution (`${KEY}`) resolves at compose time.
"""
import os
import sys

import questionary
from dotenv import dotenv_values, set_key

from .paths import PATHS

DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


def _prompt_model_config(manifest: dict, plugin_envs: dict, core_envs: dict) -> dict:
    """Prompt user to select model provider and model for this agent. Returns updated plugin_envs."""
    model_env_var = manifest.get("model_env_var")
    if not model_env_var:
        return plugin_envs

    current_provider = plugin_envs.get("COSTAFF_AGENT_MODEL_PROVIDER") or core_envs.get("COSTAFF_AGENT_MODEL_PROVIDER", "gemini")
    current_model = plugin_envs.get(model_env_var) or core_envs.get(model_env_var, "")

    provider = questionary.select(
        f"Model provider for {manifest.get('name', 'this agent')}:",
        choices=["gemini", "litellm"],
        default=current_provider,
    ).ask()
    if not provider:
        return plugin_envs

    plugin_envs["COSTAFF_AGENT_MODEL_PROVIDER"] = provider

    if provider == "gemini":
        model = questionary.text(
            "Gemini model name:",
            default=current_model or DEFAULT_GEMINI_MODEL,
        ).ask()
        if model:
            plugin_envs[model_env_var] = model

    elif provider == "litellm":
        model = questionary.text(
            "LiteLLM model name (e.g. openai/gpt-4o):",
            default=current_model or "",
        ).ask()
        api_base = questionary.text(
            "LiteLLM API base URL:",
            default=plugin_envs.get("LITELLM_API_BASE") or core_envs.get("LITELLM_API_BASE", ""),
        ).ask()
        api_key = questionary.password("LiteLLM API key:").ask()
        if model:
            plugin_envs[model_env_var] = model
            plugin_envs["LITELLM_MODEL_NAME"] = model
        if api_base:
            plugin_envs["LITELLM_API_BASE"] = api_base
        if api_key:
            plugin_envs["LITELLM_API_KEY"] = api_key

    return plugin_envs


def _prompt_and_write_plugin_env(manifest: dict, fragment_dir: str, predefined_envs: dict = None,
                                 name: str = None, core_env_path: str = None,
                                 container_prefix: str = "costaff") -> str:
    """Prompt user for env vars defined in manifest and write to plugin .env. Returns plugin env path.

    `name` is the plugin's stable id (e.g. "telegram", "coding"). Required for the
    Specialist-path env injection at the end; if omitted, falls back to the
    manifest's `name` field with the `costaff-agent-`/`costaff-channel-` prefix
    stripped.

    `core_env_path` / `container_prefix` target a specific core's .env and
    container naming (multi-core hosts); defaults preserve the single-install
    behaviour.
    """
    core_env_path = core_env_path or PATHS["env"]
    if name is None:
        manifest_name = manifest.get("name", "")
        for prefix in ("costaff-agent-", "costaff-channel-"):
            if manifest_name.startswith(prefix):
                name = manifest_name[len(prefix):]
                break
        else:
            name = manifest_name or "plugin"
    plugin_env_path = os.path.join(fragment_dir, ".env")
    core_envs = dict(dotenv_values(core_env_path))
    plugin_envs = dict(dotenv_values(plugin_env_path)) if os.path.exists(plugin_env_path) else {}

    if predefined_envs:
        plugin_envs.update(predefined_envs)

    env_required = manifest.get("env_required", [])
    env_optional = manifest.get("env_optional", [])

    # Required vars — always prompt if missing
    for k in env_required:
        current = plugin_envs.get(k) or core_envs.get(k, "")
        if not current:
            val = questionary.password(f"[Required] {k}:").ask()
            if not val:
                raise ValueError(f"Required env var {k} not provided")
            plugin_envs[k] = val
        elif sys.stdin.isatty() and (not predefined_envs or k not in predefined_envs):
            update = questionary.confirm(f"[Required] {k} is already set. Update?", default=False).ask()
            if update:
                val = questionary.password(f"{k}:", default="").ask()
                if val:
                    plugin_envs[k] = val

    # Model config — only for agents (manifest has model_env_var)
    if manifest.get("model_env_var") and sys.stdin.isatty():
        plugin_envs = _prompt_model_config(manifest, plugin_envs, core_envs)

    # Optional vars — ask if user wants to configure
    if env_optional and sys.stdin.isatty():
        configure_optional = questionary.confirm("Configure optional variables?", default=False).ask()
        if configure_optional:
            for k in env_optional:
                current = plugin_envs.get(k) or core_envs.get(k, "")
                val = questionary.text(f"[Optional] {k}:", default=current).ask()
                if val is not None:
                    plugin_envs[k] = val

    # Write plugin .env
    os.makedirs(fragment_dir, exist_ok=True)
    with open(plugin_env_path, "w") as f:
        for k, v in plugin_envs.items():
            f.write(f"{k}={v}\n")
        # Ensure Specialist path context is available for ADK Template injection.
        # The shared-dir segment must match deploy's container name
        # (<prefix>-agent-<name>) or the agent writes to a directory nobody reads.
        NAME_UPPER = name.upper().replace("-", "_")
        f.write(f"COSTAFF_SHARED_DIR_{NAME_UPPER}=/app/data/shared/{container_prefix}-agent-{name}\n")
        f.write(f"AGENT_WORKSPACE_DIR_{NAME_UPPER}=/app/data\n")

    # Also write required vars to core .env for YAML variable substitution.
    # Use quote_mode="never" (matching services/config.py): the default
    # quote_mode mangles values with shell-style escaping on rewrite, which
    # corrupts secrets like GOOGLE_API_KEY and breaks docker compose's .env parse.
    for k in env_required:
        if plugin_envs.get(k):
            set_key(core_env_path, k, plugin_envs[k], quote_mode="never")

    return plugin_env_path
