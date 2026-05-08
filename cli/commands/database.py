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
    engine = DatabaseManager.get_engine()
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
        return console.print("File not found.")
    with open(file_path, "r") as f:
        data = json.load(f)
    if not questionary.confirm("Overwrite existing data?").ask():
        return
    engine = DatabaseManager.get_engine()
    with engine.connect() as conn:
        for t, rows in data.get("tables", {}).items():
            if not rows:
                continue
            conn.execute(text(f"DELETE FROM {t}"))
            cols = rows[0].keys()
            conn.execute(text(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join([':'+c for c in cols])})"), rows)
        conn.commit()
    console.print("Restore complete.")


@db_app.command("clean")
def clean():
    """Wipe database data."""
    if questionary.confirm("Wipe all data?").ask():
        engine = DatabaseManager.get_engine()
        tables = ["events", "sessions", "user_states", "reminders", "regular_works", "epics", "stories", "project_tasks", "task_comments", "diary", "identity_maps", "file_tasks", "user_contacts", "contacts"]
        with engine.connect() as conn:
            for t in tables:
                try:
                    conn.execute(text(f"DELETE FROM {t}"))
                except Exception as e:
                    console.print(f"[yellow]Skipping {t}: {e}[/yellow]")
            conn.commit()
        console.print("Database wiped.")
