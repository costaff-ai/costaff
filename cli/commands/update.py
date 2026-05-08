import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from utils.paths import _project_root

console = Console()


def update():
    """Pull the latest CoStaff updates from GitHub."""
    console.print(Panel.fit("🔄 [bold blue]CoStaff Update[/bold blue]"))
    console.print(f"Pulling latest changes in [bold]{_project_root}[/bold]...")

    # Check for local modifications
    status = subprocess.run(["git", "status", "--porcelain"], cwd=_project_root, capture_output=True, text=True)
    if status.stdout.strip():
        console.print("[yellow]Warning: You have local modifications. Updates may fail.[/yellow]")
        console.print("[dim]Hint: Run 'git checkout .' to discard local changes if you get a conflict.[/dim]")

    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=_project_root,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        console.print(result.stdout.rstrip())
    
    if result.returncode != 0:
        if result.stderr:
            console.print(f"[red]{result.stderr.rstrip()}[/red]")
        console.print("\n[bold red]Update failed.[/bold red]")
        if "not a git repository" in result.stderr:
            console.print("[yellow]Error: CoStaff is not installed as a git repository. Manual update required.[/yellow]")
        elif "local changes to the following files" in result.stderr:
            console.print("[yellow]Error: Conflicting local changes detected.[/yellow]")
            console.print("To fix, run: [bold cyan]git checkout .[/bold cyan] and then try [bold cyan]costaff update[/bold cyan] again.")
        raise SystemExit(1)

    console.print("[bold green]Up to date! Run 'costaff restart' to apply any changes.[/bold green]")

    # Re-install CLI in-place so new dependencies take effect
    pip = str(Path(sys.executable).parent / "pip")
    console.print("Re-installing CLI dependencies...")
    subprocess.run([pip, "install", "-e", _project_root, "-q"], check=False)
    console.print("[green]Done.[/green]")
