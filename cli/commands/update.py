import subprocess
import sys

from rich.console import Console
from rich.panel import Panel

from utils.helpers import _project_root

console = Console()


def update():
    """Pull the latest CoStaff updates from GitHub."""
    console.print(Panel.fit("🔄 [bold blue]CoStaff Update[/bold blue]"))
    console.print(f"Pulling latest changes in [bold]{_project_root}[/bold]...")

    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=_project_root,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        console.print(result.stdout.rstrip())
    if result.stderr:
        console.print(f"[yellow]{result.stderr.rstrip()}[/yellow]")

    if result.returncode != 0:
        console.print("[red]Update failed. Check the output above.[/red]")
        raise SystemExit(1)

    console.print("[bold green]Up to date! Run 'costaff start' to apply any changes.[/bold green]")

    # Re-install CLI in-place so new dependencies take effect
    pip = str(__import__("pathlib").Path(sys.executable).parent / "pip")
    console.print("Re-installing CLI dependencies...")
    subprocess.run([pip, "install", "-e", _project_root, "-q"], check=False)
    console.print("[green]Done.[/green]")
