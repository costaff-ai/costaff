"""costaff bootstrap — non-interactive one-shot deploy.

Writes the minimum env vars CoStaff needs (model provider, Gemini key,
model name, language) without going through the interactive `costaff
onboard` wizard, then chains into `costaff start`.

Intended for automated / CI deployments where the Gemini API key is
available up front. For interactive setup, use `costaff onboard`
followed by `costaff start`.
"""
import os
import shutil

import typer
from dotenv import set_key
from rich.console import Console
from rich.panel import Panel

from utils.paths import PATHS, _project_root
from cli.commands.lifecycle import start as _start_command

console = Console()


def bootstrap(
    gemini_key: str = typer.Option(
        None,
        "--gemini-key", "-k",
        envvar="GOOGLE_API_KEY",
        help="Google Gemini API key. Falls back to the GOOGLE_API_KEY env var if unset.",
    ),
    gemini_model: str = typer.Option(
        "gemini-3-flash-preview",
        "--gemini-model",
        help="Gemini model name.",
    ),
    language: str = typer.Option(
        "Traditional Chinese (繁體中文)",
        "--language",
        help="Preferred response language (sets COSTAFF_PREFERRED_LANGUAGE).",
    ),
    build: bool = typer.Option(
        True,
        "--build/--no-build",
        help="Pass-through to `costaff start`: build images before launching.",
    ),
    no_start: bool = typer.Option(
        False,
        "--no-start",
        help="Write config only; skip `costaff start`.",
    ),
):
    """Non-interactive one-shot deploy: write env, then start services."""
    console.print(Panel.fit("🚀 [bold blue]CoStaff Bootstrap[/bold blue]"))

    # Ensure .env exists (mirrors `costaff onboard`).
    os.makedirs(os.path.dirname(PATHS["env"]), exist_ok=True)
    if not os.path.exists(PATHS["env"]):
        template_path = os.path.join(_project_root, ".env.template")
        if os.path.exists(template_path):
            shutil.copy(template_path, PATHS["env"])
            console.print(f"[green]Created {PATHS['env']} from template.[/green]")
        else:
            console.print(
                f"[red]Error:[/red] neither {PATHS['env']} nor {template_path} exists."
            )
            raise typer.Exit(code=1)

    if not gemini_key:
        console.print(
            "[red]Error:[/red] --gemini-key (or GOOGLE_API_KEY env var) is required.\n"
            "Run [bold]costaff onboard[/bold] for the interactive setup instead."
        )
        raise typer.Exit(code=1)

    # Write env vars to match what `costaff onboard` (gemini branch) produces.
    set_key(PATHS["env"], "COSTAFF_AGENT_MODEL_PROVIDER", "gemini", quote_mode="never")
    set_key(PATHS["env"], "GOOGLE_API_KEY", gemini_key, quote_mode="never")
    set_key(PATHS["env"], "COSTAFF_AGENT_GEMINI_MODEL", gemini_model, quote_mode="never")
    set_key(PATHS["env"], "COSTAFF_PREFERRED_LANGUAGE", language)

    # Same first-run repairs `costaff onboard` performs — a CI deploy must
    # not run with the template ID_SALT, unauthenticated internal APIs, the
    # default Postgres password, or a missing workspace bind-mount path.
    from services.preflight import (
        ensure_postgres_password,
        ensure_security_keys,
        ensure_workspace_dir,
    )
    generated = ensure_security_keys(PATHS["env"])
    if ensure_workspace_dir(PATHS["env"]):
        generated.append("COSTAFF_WORKSPACE_DIR")
    if ensure_postgres_password(PATHS["env"]):
        generated.append("POSTGRES_PASSWORD")
    if generated:
        console.print(f"[green]✔ Generated secrets:[/green] {', '.join(generated)}")

    console.print(
        f"[green]✔ Environment configured[/green] (provider=gemini, "
        f"model={gemini_model}, lang={language})."
    )

    if no_start:
        console.print(
            "\n[yellow]--no-start specified; run [bold]costaff start[/bold] to launch services.[/yellow]"
        )
        return

    console.print("\n[bold]Starting services...[/bold]\n")
    _start_command(build=build)
