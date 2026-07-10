import os
import shutil
import subprocess

import questionary
import typer
from dotenv import dotenv_values, set_key
from rich.console import Console
from rich.panel import Panel

from services.config import ConfigManager
from services.preflight import (
    ensure_postgres_password,
    ensure_security_keys,
    ensure_workspace_dir,
)
from services.runtime import get_runtime
from utils.paths import PATHS, _project_root, _runtime_root, _base_dir

console = Console()

DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


def _existing(env: dict, key: str) -> str:
    return (env.get(key) or "").strip().strip("'\"")


def _verify_gemini_key(api_key: str) -> None:
    """Live-check the key against the Gemini API. Warn-only — never blocks."""
    try:
        import httpx
        r = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key, "pageSize": 1}, timeout=8.0,
        )
        if r.status_code == 200:
            console.print("[green]✔ Gemini API key verified.[/green]")
        elif r.status_code in (400, 401, 403):
            console.print(
                f"[yellow]⚠ Gemini rejected this key (HTTP {r.status_code}). "
                "Double-check it at https://aistudio.google.com/apikey — "
                "you can re-run `costaff onboard` to fix it.[/yellow]"
            )
        else:
            console.print(f"[yellow]⚠ Could not verify key (HTTP {r.status_code}); continuing.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Key verification skipped (network issue: {e}).[/yellow]")


def _setup_dashboard_admin() -> None:
    """Create the operator-dashboard login if it doesn't exist yet."""
    from services.auth import AuthManager

    if AuthManager.get_auth() is not None:
        return
    console.print(Panel.fit("🔐 [bold blue]Dashboard Admin Account[/bold blue]"))
    console.print(
        "[dim]Used to log into the web dashboard (costaff dashboard). "
        "Skip to set it up in the browser on first visit instead.[/dim]"
    )
    if not questionary.confirm("Create the dashboard admin account now?", default=True).ask():
        return
    username = questionary.text("Admin username:", default="admin").ask()
    if not username:
        return
    while True:
        password = questionary.password("Admin password:").ask()
        if password is None:
            return
        if len(password) < 8:
            console.print("[yellow]Password must be at least 8 characters.[/yellow]")
            continue
        confirm = questionary.password("Confirm password:").ask()
        if password == confirm:
            break
        console.print("[yellow]Passwords do not match — try again.[/yellow]")
    AuthManager.save_auth(username, password)
    console.print(f"[green]✔ Dashboard admin '{username}' created.[/green]")


def _print_next_steps() -> None:
    console.print(Panel.fit(
        "[bold]1.[/bold] [green]costaff start[/green]        — boot Postgres → agents → manager → channels\n"
        "[bold]2.[/bold] [green]costaff dashboard[/green]    — open http://localhost:8501 and click [bold]Chat[/bold]\n"
        "[bold]3.[/bold] Say hi! Try: [italic]\"Remind me to drink water at 3 PM every day\"[/italic]\n"
        "\n"
        "[dim]Something off? `costaff doctor` writes a full diagnostic report.\n"
        "Re-run `costaff onboard` anytime — existing settings are kept as defaults.[/dim]",
        title="🎉 Setup complete — next steps",
        border_style="green",
    ))


def onboard():
    """Run configuration wizard."""
    import sys
    if not sys.stdin.isatty():
        # Under `curl … | bash` (or any pipe) every questionary prompt EOFs
        # to None and we'd write a half-empty .env. Refuse instead.
        console.print(
            "[red]costaff onboard is interactive and needs a terminal (TTY).[/red]\n"
            "Run [bold]costaff onboard[/bold] directly in your shell, or use "
            "[bold]costaff bootstrap --gemini-key <key>[/bold] for non-interactive setup."
        )
        raise typer.Exit(1)
    os.makedirs(os.path.dirname(PATHS["env"]), exist_ok=True)
    if not os.path.exists(PATHS["env"]):
        template_path = os.path.join(_project_root, ".env.template")
        if os.path.exists(template_path):
            shutil.copy(template_path, PATHS["env"])
            console.print(f"[bold green]Created {PATHS['env']} from template.[/bold green]")
        else:
            # Create a blank file if template is not found
            with open(PATHS["env"], "w") as f:
                pass
            console.print(f"[yellow]Warning: {template_path} not found. Created a blank {PATHS['env']}.[/yellow]")

    # First-run env repair BEFORE any prompt: the DB-URI default below must
    # interpolate the (possibly freshly rotated) Postgres password, and the
    # compose bind mount hard-requires COSTAFF_WORKSPACE_DIR.
    if ensure_workspace_dir(PATHS["env"]):
        console.print("[green]Security: COSTAFF_WORKSPACE_DIR written to .env.[/green]")
    if ensure_postgres_password(PATHS["env"]):
        console.print("[green]Security: generated a random Postgres password (fresh install).[/green]")

    # Re-running onboard must never wipe a working setup: every prompt below
    # defaults to the value already in .env.
    env = dotenv_values(PATHS["env"])

    console.print(Panel.fit("🤖 [bold blue]CoStaff Onboarding[/bold blue]"))
    pg_user = _existing(env, "POSTGRES_USER") or "costaff"
    pg_pass = _existing(env, "POSTGRES_PASSWORD") or "costaff_pass"
    pg_db = _existing(env, "POSTGRES_DB") or "costaff_db"
    db_uri = questionary.text(
        "PostgreSQL URI:",
        default=_existing(env, "ADK_SESSION_SERVICE_URI")
        or f"postgresql+asyncpg://{pg_user}:{pg_pass}@postgres:5432/{pg_db}"
    ).ask()

    console.print(Panel.fit("🤖 [bold blue]Model Configuration[/bold blue]"))
    provider_choices = [
        questionary.Choice("Google Gemini (free tier works — recommended)", value="gemini"),
        questionary.Choice("LiteLLM (for OpenAI, Anthropic, Ollama, etc.)", value="litellm"),
    ]
    current_provider = _existing(env, "COSTAFF_AGENT_MODEL_PROVIDER")
    default_choice = next((c for c in provider_choices if c.value == current_provider), None)
    model_provider = questionary.select(
        "Select Model Provider:", choices=provider_choices, default=default_choice,
    ).ask()

    if model_provider == "gemini":
        set_key(PATHS["env"], "COSTAFF_AGENT_MODEL_PROVIDER", "gemini")
        existing_key = _existing(env, "GOOGLE_API_KEY")
        prompt = "Google API Key (https://aistudio.google.com/apikey):"
        if existing_key:
            prompt = f"Google API Key (Enter to keep current ****{existing_key[-4:]}):"
        api_key = questionary.password(prompt).ask()
        if api_key:
            set_key(PATHS["env"], "GOOGLE_API_KEY", api_key)
        effective_key = api_key or existing_key
        if effective_key:
            _verify_gemini_key(effective_key)
        else:
            console.print(
                "[yellow]⚠ No API key set — `costaff start` will refuse to launch "
                "until one is configured.[/yellow]"
            )
        model_name = questionary.text(
            "Gemini Model Name:",
            default=_existing(env, "COSTAFF_AGENT_GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        ).ask()
        if model_name:
            set_key(PATHS["env"], "COSTAFF_AGENT_GEMINI_MODEL", model_name)

    elif model_provider == "litellm":
        set_key(PATHS["env"], "COSTAFF_AGENT_MODEL_PROVIDER", "litellm")
        model_name = questionary.text(
            "LiteLLM Model Name (e.g., ollama/llama3, openai/gpt-4o-mini):",
            default=_existing(env, "LITELLM_MODEL_NAME") or "ollama/llama3",
        ).ask()
        if model_name:
            set_key(PATHS["env"], "LITELLM_MODEL_NAME", model_name)
        api_base = questionary.text(
            "LiteLLM API Base URL (e.g., http://host.docker.internal:11434 for Ollama):",
            default=_existing(env, "LITELLM_API_BASE"),
        ).ask()
        if api_base:
            set_key(PATHS["env"], "LITELLM_API_BASE", api_base)
        api_key = questionary.password("LiteLLM API Key (optional, Enter to keep/skip):").ask()
        if api_key:
            set_key(PATHS["env"], "LITELLM_API_KEY", api_key)
        skip_special = questionary.confirm("Skip special tokens?", default=False).ask()
        set_key(PATHS["env"], "LITELLM_SKIP_SPECIAL_TOKENS", "True" if skip_special else "False")

    console.print(Panel.fit("🌏 [bold blue]System Configuration[/bold blue]"))

    # Language Selection
    lang_values = [
        "Traditional Chinese (繁體中文)", "English",
        "Japanese (日本語)", "Simplified Chinese (简体中文)",
    ]
    current_lang = _existing(env, "COSTAFF_PREFERRED_LANGUAGE")
    lang_choice = questionary.select(
        "Preferred Response Language (回覆語系):",
        choices=lang_values,
        default=current_lang if current_lang in lang_values else "Traditional Chinese (繁體中文)",
    ).ask()
    if lang_choice:
        set_key(PATHS["env"], "COSTAFF_PREFERRED_LANGUAGE", lang_choice)

    common_timezones = [
        "UTC", "Asia/Taipei", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore",
        "Asia/Seoul", "Asia/Hong_Kong", "America/New_York", "America/Los_Angeles",
        "America/Chicago", "Europe/London", "Europe/Paris", "Europe/Berlin",
        "Australia/Sydney", "Custom..."
    ]
    current_tz = _existing(env, "TIMEZONE")
    tz_choice = questionary.select(
        "Timezone:", choices=common_timezones,
        default=current_tz if current_tz in common_timezones else "UTC",
    ).ask()
    if tz_choice == "Custom...":
        tz_choice = questionary.text(
            "Enter timezone (pytz format, e.g. America/Toronto):",
            default=current_tz or "UTC",
        ).ask()
    if tz_choice:
        set_key(PATHS["env"], "TIMEZONE", tz_choice)

    already_deployed = set(ConfigManager.get_config().get("dynamic_channels", {}).keys())
    platforms = questionary.checkbox(
        "Select Channels to enable (官方通訊頻道):",
        choices=[
            questionary.Choice(
                "WebChat (網頁版對話) — recommended: chat from the browser, no bot token needed",
                value="webchat",
                checked="webchat" in already_deployed or not already_deployed,
            ),
            questionary.Choice("Telegram", value="telegram", checked="telegram" in already_deployed),
            questionary.Choice("Discord", value="discord", checked="discord" in already_deployed),
            questionary.Choice("Line", value="line", checked="line" in already_deployed),
            questionary.Choice("Email (SMTP - 系統通知用)", value="email"),
        ]
    ).ask()

    set_key(PATHS["env"], "ADK_SESSION_SERVICE_URI", db_uri)

    for key in ensure_security_keys(PATHS["env"]):
        console.print(f"[green]Security: generated {key}.[/green]")

    # docker-compose.yaml lives in _project_root (= _runtime_root = ~/.costaff)
    # No copy or path-rewriting needed.
    costaff_dir = _runtime_root
    dest_compose = os.path.join(costaff_dir, "docker-compose.yaml")

    conf = ConfigManager.get_config()
    conf.setdefault("dynamic_channels", {})

    if platforms:
        from cli.commands.channel import OFFICIAL_CHANNELS
        from utils.deploy import _deploy_local_channel

        for p in platforms:
            if p in already_deployed:
                console.print(f"[dim]Channel '{p}' already deployed — keeping it.[/dim]")
                continue
            if p == "email":
                # Email is still a legacy system service for now
                server_addr = questionary.text("SMTP Server (e.g. smtp.gmail.com):").ask()
                # ... (rest of email setup)
                continue

            # For Official Dynamic Channels:
            if p in OFFICIAL_CHANNELS:
                console.print(f"\n🚀 [bold]Configuring {p.capitalize()} Channel...[/bold]")
                envs = {}
                if p == "telegram":
                    token = questionary.password("Telegram Bot Token:").ask()
                    if token: envs["TELEGRAM_BOT_TOKEN"] = token
                elif p == "discord":
                    token = questionary.password("Discord Bot Token:").ask()
                    if token: envs["DISCORD_BOT_TOKEN"] = token
                elif p == "line":
                    token = questionary.password("Line Channel Access Token:").ask()
                    secret = questionary.password("Line Channel Secret:").ask()
                    if token: envs["LINE_CHANNEL_ACCESS_TOKEN"] = token
                    if secret: envs["LINE_CHANNEL_SECRET"] = secret

                # Auto-deploy via GitHub
                repo_url = OFFICIAL_CHANNELS[p]
                target_src = os.path.join(_base_dir, "costaff-channel", p, "src")

                if not os.path.exists(target_src):
                    os.makedirs(os.path.dirname(target_src), exist_ok=True)
                    subprocess.run(["git", "clone", "--depth", "1", repo_url, target_src], check=True)

                try:
                    entry = _deploy_local_channel(p, target_src, conf, predefined_envs=envs, build_only=True)
                    conf["dynamic_channels"][p] = entry
                except Exception as e:
                    console.print(f"[red]Failed to deploy {p}: {e}[/red]")
                    console.print(
                        f"[yellow]You can retry later with: costaff channel add {p}[/yellow]"
                    )

    conf.update({
        "channels": [p for p in (platforms or []) if p not in ["email", "telegram", "line", "discord", "webchat"]], # legacy empty
        "model_provider": model_provider,
    })
    conf.setdefault("external_agents", {})
    if "mcp" not in conf or not conf["mcp"]:
        conf["mcp"] = ["costaff"]
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()
    ConfigManager.update_mcp_urls()

    _setup_dashboard_admin()

    console.print(Panel.fit("🤖 [bold blue]Docker Setup[/bold blue]"))

    if questionary.confirm("Do you want to build Docker images now?").ask():
        console.print("Building Docker images...")
        try:
            get_runtime().build()
        except RuntimeError as e:
            console.print(f"[red]Build failed: {e}[/red]")
            raise typer.Exit(1)

    _print_next_steps()
