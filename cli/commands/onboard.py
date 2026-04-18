import os
import shutil
import subprocess

import questionary
import typer
from dotenv import set_key
from rich.console import Console
from rich.panel import Panel

from managers.config import ConfigManager
from managers.docker import DockerManager
from utils.helpers import PATHS, _project_root, _runtime_root, _runtime_root

console = Console()


def onboard():
    """Run configuration wizard."""
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

    console.print(Panel.fit("🤖 [bold blue]CoStaff Onboarding[/bold blue]"))
    db_uri = questionary.text(
        "PostgreSQL URI:",
        default="postgresql+asyncpg://costaff:costaff_pass@postgres:5432/costaff_db"
    ).ask()

    console.print(Panel.fit("🤖 [bold blue]Model Configuration[/bold blue]"))
    model_provider = questionary.select(
        "Select Model Provider:",
        choices=[
            questionary.Choice("Google Gemini", value="gemini"),
            questionary.Choice("LiteLLM (for OpenAI, Anthropic, Ollama, etc.)", value="litellm"),
        ]
    ).ask()

    if model_provider == "gemini":
        set_key(PATHS["env"], "COSTAFF_AGENT_MODEL_PROVIDER", "gemini")
        api_key = questionary.password("Google API Key:").ask()
        if api_key:
            set_key(PATHS["env"], "GOOGLE_API_KEY", api_key)
        model_name = questionary.text("Gemini Model Name:", default="gemini-2.5-flash").ask()
        if model_name:
            set_key(PATHS["env"], "COSTAFF_AGENT_GEMINI_MODEL", model_name)

    elif model_provider == "litellm":
        set_key(PATHS["env"], "COSTAFF_AGENT_MODEL_PROVIDER", "litellm")
        model_name = questionary.text("LiteLLM Model Name (e.g., ollama/llama3):", default="ollama/llama3").ask()
        if model_name:
            set_key(PATHS["env"], "LITELLM_MODEL", model_name)
        api_base = questionary.text("LiteLLM API Base URL (e.g., http://host.docker.internal:11434 for Ollama):").ask()
        if api_base:
            set_key(PATHS["env"], "LITELLM_API_BASE", api_base)
        api_key = questionary.password("LiteLLM API Key (optional):").ask()
        if api_key:
            set_key(PATHS["env"], "LITELLM_API_KEY", api_key)
        skip_special = questionary.confirm("Skip special tokens?", default=False).ask()
        set_key(PATHS["env"], "LITELLM_SKIP_SPECIAL_TOKENS", "True" if skip_special else "False")

    console.print(Panel.fit("🌏 [bold blue]System Configuration[/bold blue]"))
    
    # Language Selection
    lang_choice = questionary.select(
        "Preferred Response Language (回覆語系):",
        choices=[
            questionary.Choice("Traditional Chinese (繁體中文)", value="Traditional Chinese (繁體中文)"),
            questionary.Choice("English", value="English"),
            questionary.Choice("Japanese (日本語)", value="Japanese (日本語)"),
            questionary.Choice("Simplified Chinese (简体中文)", value="Simplified Chinese (简体中文)"),
        ],
        default="Traditional Chinese (繁體中文)"
    ).ask()
    if lang_choice:
        set_key(PATHS["env"], "COSTAFF_PREFERRED_LANGUAGE", lang_choice)

    common_timezones = [
        "UTC", "Asia/Taipei", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore",
        "Asia/Seoul", "Asia/Hong_Kong", "America/New_York", "America/Los_Angeles",
        "America/Chicago", "Europe/London", "Europe/Paris", "Europe/Berlin",
        "Australia/Sydney", "Custom..."
    ]
    tz_choice = questionary.select("Timezone:", choices=common_timezones, default="UTC").ask()
    if tz_choice == "Custom...":
        tz_choice = questionary.text(
            "Enter timezone (pytz format, e.g. America/Toronto):", default="UTC"
        ).ask()
    if tz_choice:
        set_key(PATHS["env"], "TIMEZONE", tz_choice)

    platforms = questionary.checkbox(
        "Select Channels to enable (官方通訊頻道):",
        choices=[
            questionary.Choice("Telegram", value="telegram"),
            questionary.Choice("Discord", value="discord"),
            questionary.Choice("Line", value="line"),
            questionary.Choice("WebChat (網頁版對話)", value="webchat"),
            questionary.Choice("Email (SMTP - 系統通知用)", value="email"),
        ]
    ).ask()

    set_key(PATHS["env"], "ADK_SESSION_SERVICE_URI", db_uri)

    # Generate .costaff/docker-compose.yaml BEFORE deploying channels,
    # because channel deploy runs `docker compose -f <this file>` immediately.
    base_compose_file = "docker-compose.yaml"
    src_compose = os.path.join(_project_root, base_compose_file)
    costaff_dir = _runtime_root
    dest_compose = os.path.join(costaff_dir, base_compose_file)

    with open(src_compose, "r") as f:
        compose_content = f.read()

    compose_content = compose_content.replace(
        "build: .", "build: .."
    ).replace(
        "context: .", "context: .."
    ).replace(
        "- ./src", "- ../src"
    ).replace(
        "- ./mcp_servers", "- ../mcp_servers"
    )

    with open(dest_compose, "w") as f:
        f.write(compose_content)

    conf = ConfigManager.get_config()
    conf.setdefault("dynamic_channels", {})

    if platforms:
        from cli.commands.channel import OFFICIAL_CHANNELS
        from utils.helpers import _deploy_local_channel
        
        for p in platforms:
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
                target_src = os.path.join(_runtime_root, "src", "channels", p)
                
                if not os.path.exists(target_src):
                    os.makedirs(os.path.dirname(target_src), exist_ok=True)
                    subprocess.run(["git", "clone", "--depth", "1", repo_url, target_src], check=True)
                
                try:
                    entry = _deploy_local_channel(p, target_src, conf, predefined_envs=envs, build_only=True)
                    conf["dynamic_channels"][p] = entry
                except Exception as e:
                    console.print(f"[red]Failed to deploy {p}: {e}[/red]")

    conf.update({
        "channels": [p for p in (platforms or []) if p not in ["email", "telegram", "line", "discord", "webchat"]], # legacy empty
        "model_provider": model_provider,
    })
    conf.setdefault("external_agents", {})
    if "mcp" not in conf or not conf["mcp"]:
        conf["mcp"] = ["costaff"]
    ConfigManager.save_config(conf)
    ConfigManager.update_external_agents_env()

    console.print(Panel.fit("🤖 [bold blue]Docker Setup[/bold blue]"))
    console.print(f"[bold green]Generated {dest_compose}[/bold green]")

    if questionary.confirm("Do you want to build Docker images now?").ask():
        console.print("Building Docker images...")
        cmd = DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "build"]
        subprocess.run(cmd, check=True, cwd=costaff_dir)

    console.print("[bold green]Success! Run 'costaff start' to begin.[/bold green]")
