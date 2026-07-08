"""`costaff core ...` — Workspace/System layer (mirrors the dashboard's
System switcher).

A host can run several independent CoStaff cores (see services/cores.py).
The dashboard reflects ONE core at a time via the switcher; these commands
manage the same registry + active-core pointer from the terminal:

  costaff core list              # registered cores, active one marked
  costaff core use <name>        # switch the active core (dashboard follows)
  costaff core discover [--save] # scan running *-core compose projects
"""
import typer
from rich.console import Console
from rich.table import Table

from services import cores as core_svc
from services.config import ConfigManager

console = Console()

core_app = typer.Typer(help="Manage CoStaff cores (workspaces) — same registry the dashboard switcher uses.")


@core_app.command("list")
def core_list():
    """List registered cores; the active one is what the dashboard shows."""
    cores = core_svc.list_cores()
    table = Table(title="CoStaff Cores")
    table.add_column("", justify="center")
    table.add_column("Name", style="cyan")
    table.add_column("Label")
    table.add_column("Prefix", style="blue")
    table.add_column("Manager Port", justify="right")
    for c in cores:
        table.add_row("●" if c["active"] else "", c["name"], c["label"],
                      c["prefix"], str(c["manager_port"]))
    console.print(table)


@core_app.command("use")
def core_use(name: str = typer.Argument(..., help="Core name from `costaff core list`")):
    """Switch the active core. The dashboard and core-aware CLI commands follow."""
    try:
        core_svc.set_active(name)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Active core → {name}[/green]")


@core_app.command("discover")
def core_discover(save: bool = typer.Option(False, "--save", help="Merge discovered cores into config.json")):
    """Scan running `*-core` docker compose projects and (optionally) register them."""
    try:
        found = core_svc.discover()
    except Exception as e:
        console.print(f"[red]Discovery failed: {e}[/red]")
        raise typer.Exit(1)
    if not found:
        console.print("[yellow]No running *-core compose projects found.[/yellow]")
        return

    table = Table(title="Discovered Cores")
    table.add_column("Name", style="cyan")
    table.add_column("Label")
    table.add_column("Manager Port", justify="right")
    table.add_column("Config Path")
    for name, data in found.items():
        table.add_row(name, data["label"], str(data["manager_port"]), data["config_path"])
    console.print(table)

    if not save:
        console.print("[dim]Dry run — pass --save to register these in config.json.[/dim]")
        return
    conf = ConfigManager.get_config()
    conf.setdefault("cores", {}).update(found)
    conf.setdefault("active_core", next(iter(conf["cores"])))
    ConfigManager.save_config(conf)
    console.print(f"[green]Registered {len(found)} core(s). Active: {conf['active_core']}[/green]")
