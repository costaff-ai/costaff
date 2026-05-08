"""`costaff config ...` commands — currently just `validate`."""
import json
from pathlib import Path

import typer
from rich.console import Console

from services.config_schema import CoStaffConfig
from utils.paths import PATHS

config_app = typer.Typer(help="config.json management")
console = Console()


@config_app.command("validate")
def validate(
    path: str = typer.Option(None, "--path", help="Override config.json path"),
):
    """Validate config.json against the schema. Exits 1 if invalid."""
    target = Path(path or PATHS["config"])
    if not target.exists():
        console.print(f"[red]config.json not found at {target}[/red]")
        raise typer.Exit(1)

    try:
        raw = json.loads(target.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]config.json is not valid JSON:[/red] {e}")
        raise typer.Exit(1)

    try:
        CoStaffConfig.model_validate(raw)
    except Exception as e:
        console.print(f"[red]config.json failed validation:[/red]\n{e}")
        raise typer.Exit(1)

    console.print(f"[green]✓ config.json is valid[/green] [dim]({target})[/dim]")
