import os
import shutil
import sys

import typer
from rich.console import Console
from rich.panel import Panel

from utils.helpers import _project_root

console = Console()


def license(
    action: str = typer.Argument(..., help="apply | status"),
    path: str = typer.Argument(None, help="Path to costaff-license.yaml (for apply)"),
):
    """Manage your CoStaff Agent license."""
    sys.path.insert(0, _project_root)
    from src.core.license import LicenseManager, OSS_LIMITS

    costaff_dir = os.path.join(_project_root, ".costaff")
    dest = os.path.join(costaff_dir, "costaff-license.yaml")

    if action == "apply":
        if not path:
            console.print("[red]Please provide the path to your license file.[/red]")
            console.print("  Usage: costaff license apply ./costaff-license.yaml")
            raise typer.Exit(1)
        if not os.path.exists(path):
            console.print(f"[red]File not found: {path}[/red]")
            raise typer.Exit(1)
        try:
            info = LicenseManager.load(path)
            if info:
                shutil.copy(path, dest)
                console.print(Panel.fit(
                    f"[green]✔ License applied successfully[/green]\n\n"
                    f"  Plan              : [bold]{info.plan.upper()}[/bold]\n"
                    f"  Issued to         : {info.issued_to}\n"
                    f"  Expires           : {info.expires_at or 'Never'}\n"
                    f"  extra_mcp         : {info.extra_mcp}\n"
                    f"  monthly_executions: {info.monthly_executions}\n"
                    f"  max_users         : {info.max_users}\n"
                    f"  enabled_channels  : {info.enabled_channels}\n"
                    f"  max_apis          : {info.max_apis}\n"
                    f"  max_skills        : {info.max_skills}",
                    title="CoStaff License"
                ))
        except ValueError as e:
            console.print(f"[red]✖ License rejected: {e}[/red]")
            raise typer.Exit(1)

    elif action == "machine-id":
        from src.core.license import get_machine_id
        mid = get_machine_id()
        console.print(Panel.fit(
            f"  Machine ID : [bold]{mid}[/bold]\n\n"
            f"  Provide this to the licensor when purchasing an Enterprise License.",
            title="CoStaff Machine ID"
        ))

    elif action == "status":
        if os.path.exists(dest):
            try:
                info = LicenseManager.load(dest)
                expired_note = " [red](EXPIRED)[/red]" if info and info.is_expired else ""
                console.print(Panel.fit(
                    f"  Plan              : [bold]{info.plan.upper()}[/bold]{expired_note}\n"
                    f"  Issued to         : {info.issued_to}\n"
                    f"  Expires           : {info.expires_at or 'Never'}\n"
                    f"  extra_mcp         : {info.extra_mcp}\n"
                    f"  monthly_executions: {info.monthly_executions}\n"
                    f"  max_users         : {info.max_users}\n"
                    f"  enabled_channels  : {info.enabled_channels}\n"
                    f"  max_apis          : {info.max_apis}\n"
                    f"  max_skills        : {info.max_skills}",
                    title="CoStaff License"
                ))
            except ValueError as e:
                console.print(f"[red]License invalid: {e}[/red]")
        else:
            console.print(Panel.fit(
                f"  Plan              : [bold]OSS[/bold]\n"
                f"  extra_mcp         : {OSS_LIMITS['extra_mcp']}\n"
                f"  monthly_executions: {OSS_LIMITS['monthly_executions']}\n"
                f"  max_users         : {OSS_LIMITS['max_users']}\n"
                f"  enabled_channels  : {OSS_LIMITS['enabled_channels']}\n"
                f"  max_apis          : {OSS_LIMITS['max_apis']}\n"
                f"  max_skills        : {OSS_LIMITS['max_skills']}\n\n"
                f"  To upgrade, contact: simonliuyuwei@gmail.com",
                title="CoStaff License"
            ))
    else:
        console.print(f"[red]Unknown action: {action}. Use 'apply' or 'status'.[/red]")
        raise typer.Exit(1)
