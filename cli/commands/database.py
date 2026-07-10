import json
import time
from datetime import datetime

import questionary
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from services.database import DatabaseManager
from utils.paths import VERSION

console = Console()

db_app = typer.Typer(help="Manage database.")


def _require_engine():
    """Return the DB engine, or print a friendly message and exit.

    get_engine() returns None when ADK_SESSION_SERVICE_URI is unset. Without
    this guard backup/clean/restore called .connect() on None and dumped a
    raw AttributeError traceback (db migrate/history already handled this).
    """
    engine = DatabaseManager.get_engine()
    if engine is None:
        console.print("[red]No database configured (ADK_SESSION_SERVICE_URI missing in .env).[/red]")
        console.print("[dim]Run `costaff onboard`, or start the stack with `costaff start`.[/dim]")
        raise typer.Exit(1)
    return engine


@db_app.command("info")
def info():
    """Show DB info and statistics."""
    counts = DatabaseManager.get_table_counts()
    table = Table(title="Database Stats")
    table.add_column("Table", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for t, c in counts.items():
        table.add_row(t, str(c))
    console.print(table)


@db_app.command("backup")
def backup(output: str = typer.Argument(None)):
    """Create full DB backup."""
    output = output or f"costaff_backup_{int(time.time())}.json"
    engine = _require_engine()
    tables = ["events", "sessions", "user_states", "reminders", "regular_works", "epics", "stories", "project_tasks", "task_comments", "diary", "identity_maps", "file_tasks", "user_contacts", "contacts"]
    data = {"version": VERSION, "timestamp": datetime.now().isoformat(), "tables": {}}
    with engine.connect() as conn:
        for t in tables:
            try:
                res = conn.execute(text(f"SELECT * FROM {t}"))
                rows = [dict(row._mapping) for row in res]
                for r in rows:
                    for k, v in r.items():
                        if isinstance(v, datetime):
                            r[k] = v.isoformat()
                data["tables"][t] = rows
            except Exception as e:
                console.print(f"[yellow]Skipping table {t}: {e}[/yellow]")
    with open(output, "w") as f:
        json.dump(data, f, indent=2)
    console.print(f"Backup saved to {output}")


@db_app.command("restore")
def restore(file_path: str):
    """Restore from JSON backup."""
    import os
    if not os.path.exists(file_path):
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)
    engine = _require_engine()
    with open(file_path, "r") as f:
        data = json.load(f)
    if not questionary.confirm("Overwrite existing data?").ask():
        return
    with engine.connect() as conn:
        for t, rows in data.get("tables", {}).items():
            if not rows:
                continue
            conn.execute(text(f"DELETE FROM {t}"))
            cols = rows[0].keys()
            conn.execute(text(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join([':'+c for c in cols])})"), rows)
        conn.commit()
    console.print("Restore complete.")


def _host_alembic_config():
    """Build an alembic Config pointed at the host-reachable DB URL.

    Returns None when no database is configured. The host can't resolve the
    ``postgres`` compose hostname, so we reuse DatabaseManager's localhost
    rewrite and hand the URL to alembic via COSTAFF_ALEMBIC_URL.
    """
    import os

    from alembic.config import Config

    from utils.paths import _project_root

    engine = DatabaseManager.get_engine()
    if engine is None:
        return None
    os.environ["COSTAFF_ALEMBIC_URL"] = engine.url.render_as_string(hide_password=False)
    cfg = Config(os.path.join(_project_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_project_root, "migrations"))
    return cfg


@db_app.command("migrate")
def migrate():
    """Apply pending schema migrations (alembic upgrade head)."""
    from alembic import command

    cfg = _host_alembic_config()
    if cfg is None:
        console.print("[red]No database configured (ADK_SESSION_SERVICE_URI missing in .env).[/red]")
        raise typer.Exit(1)
    try:
        command.upgrade(cfg, "head")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Migration failed: {e}[/red]")
        console.print("[dim]Is the postgres container running? Try 'costaff start'.[/dim]")
        raise typer.Exit(1)
    console.print("[green]Database is at head.[/green]")


@db_app.command("history")
def history():
    """Show migration history with the current revision marked."""
    from alembic import command

    cfg = _host_alembic_config()
    if cfg is None:
        console.print("[red]No database configured (ADK_SESSION_SERVICE_URI missing in .env).[/red]")
        raise typer.Exit(1)
    try:
        command.history(cfg, indicate_current=True)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Could not read history: {e}[/red]")
        raise typer.Exit(1)


@db_app.command("clean")
def clean():
    """Wipe database data."""
    if questionary.confirm("Wipe all data?").ask():
        engine = _require_engine()
        tables = ["events", "sessions", "user_states", "reminders", "regular_works", "epics", "stories", "project_tasks", "task_comments", "diary", "identity_maps", "file_tasks", "user_contacts", "contacts"]
        with engine.connect() as conn:
            for t in tables:
                try:
                    conn.execute(text(f"DELETE FROM {t}"))
                except Exception as e:
                    console.print(f"[yellow]Skipping {t}: {e}[/yellow]")
            conn.commit()
        console.print("Database wiped.")
