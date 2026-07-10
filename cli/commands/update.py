import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from services.runtime.git import Git, GitError
from utils.paths import _project_root

console = Console()

# Changes under these paths ship INSIDE the manager-core images (built from
# _project_root's compose), so `costaff restart` — which recreates without
# rebuilding — won't pick them up. A new alembic migration also runs only on
# mcp-costaff startup, i.e. after a rebuild. `cli/`, `server/`, `utils/`,
# `services/` are host-side (the CLI reinstall above applies them), so they
# are deliberately NOT here.
_CORE_IMAGE_PATHS = ("mcp_servers/", "migrations/", "agents/", "requirements.txt", "Dockerfile")


def _head_rev() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_project_root,
                       capture_output=True, text=True)
    return r.stdout.strip()


def _core_images_changed(before: str, after: str) -> list[str]:
    """Paths under _CORE_IMAGE_PATHS that changed between two revs."""
    if not before or not after or before == after:
        return []
    diff = subprocess.run(["git", "diff", "--name-only", before, after],
                          cwd=_project_root, capture_output=True, text=True)
    changed = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]
    return [f for f in changed if f.startswith(_CORE_IMAGE_PATHS)]


def _guide_core_rebuild(changed: list[str]) -> None:
    """Tell the user (and, on a TTY, offer to run) the core rebuild that a
    plain `restart` cannot substitute for."""
    import questionary

    has_migration = any(f.startswith("migrations/") for f in changed)
    console.print(Panel.fit(
        "🧱 [bold yellow]Core image changes detected[/bold yellow]\n"
        f"{len(changed)} file(s) under "
        + ", ".join(sorted({f.split('/')[0] for f in changed}))
        + " ship inside the manager-core images.\n"
        + ("A new database migration was included — it runs on "
           "mcp-costaff startup, i.e. after a rebuild.\n" if has_migration else "")
        + "[dim]`costaff restart` recreates containers but does NOT rebuild "
          "images, so it will run the old code/schema.[/dim]"
    ))
    if sys.stdin.isatty() and questionary.confirm(
        "Rebuild the manager core now (costaff core-rebuild)?", default=True
    ).ask():
        from cli.commands.lifecycle import core_rebuild
        core_rebuild(no_cache=False)
    else:
        console.print("[yellow]Run [bold]costaff core-rebuild[/bold] to apply "
                      "(a plain restart is not enough).[/yellow]")


def update(
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin CoStaff core to a release tag, branch, or commit (e.g. v0.1.0-alpha-1). Without this flag the command fast-forwards to whatever main currently points at."),
    all_plugins: bool = typer.Option(False, "--all", help="After updating the core, re-pin and rebuild every registered agent and channel to the same --tag (or pull latest when no --tag). Requires Docker — this rebuilds containers."),
):
    """Pull the latest CoStaff updates from GitHub."""
    if tag:
        console.print(Panel.fit(f"🔄 [bold blue]CoStaff Update[/bold blue] → [magenta]{tag}[/magenta]"))
    else:
        console.print(Panel.fit("🔄 [bold blue]CoStaff Update[/bold blue]"))
    console.print(f"Pulling latest changes in [bold]{_project_root}[/bold]...")

    # Snapshot HEAD so we can tell afterwards whether the update touched code
    # that lives inside the manager-core images (needs a rebuild, not a plain
    # restart).
    rev_before = _head_rev()

    # Check for local modifications
    status = subprocess.run(["git", "status", "--porcelain"], cwd=_project_root, capture_output=True, text=True)
    if status.stdout.strip():
        console.print("[yellow]Warning: You have local modifications. Updates may fail.[/yellow]")
        console.print("[dim]Hint: Run 'git checkout .' to discard local changes if you get a conflict.[/dim]")

    if tag:
        # Tag-pinned path: fetch refs + tags, then check out. We do NOT
        # pull/merge — that would refuse on detached HEAD anyway. After
        # checkout the working tree is detached at the tag/commit (or
        # attached if `tag` happens to be a branch name); either is fine
        # for a runtime install.
        git = Git()
        try:
            git.fetch_tags(_project_root)
            git.checkout(_project_root, tag)
        except GitError as e:
            console.print(f"[red]{e}[/red]")
            console.print("\n[bold red]Update failed.[/bold red]")
            raise SystemExit(1)
        console.print(f"[bold green]Checked out {tag}.[/bold green] Run 'costaff restart' to apply any changes.")
    else:
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

    # If the update changed code/migrations baked into the core images, a
    # plain `restart` silently runs the old image — guide the rebuild.
    changed = _core_images_changed(rev_before, _head_rev())
    if changed:
        _guide_core_rebuild(changed)

    if all_plugins:
        _update_all_plugins(tag)


def _update_all_plugins(tag: Optional[str]) -> None:
    """Re-pin + rebuild every source-based agent and channel to `tag`.

    Reuses the per-plugin `agent rebuild` / `channel rebuild` commands so the
    git-checkout, config-pin, and container-rebuild semantics stay identical
    to running them by hand. Each plugin is isolated: a failure on one is
    reported and the loop moves on instead of aborting the whole batch.
    Remote (`type: "url"`) agents have no source tree to check out and are
    skipped.
    """
    # Lazy imports avoid any import cycle at CLI load time.
    from services.config import ConfigManager
    from cli.commands.agent_container import agent_rebuild
    from cli.commands.channel import channel_rebuild

    conf = ConfigManager.get_config()
    agents = [
        n for n, e in conf.get("external_agents", {}).items()
        if e.get("type") == "github" and e.get("fragment_path")
    ]
    channels = [
        n for n, e in conf.get("dynamic_channels", {}).items()
        if e.get("fragment_path")
    ]
    skipped = [
        n for n, e in conf.get("external_agents", {}).items()
        if e.get("type") != "github" or not e.get("fragment_path")
    ]

    total = len(agents) + len(channels)
    if total == 0:
        console.print("[dim]No source-based agents or channels to rebuild.[/dim]")
        return

    target = f"→ [magenta]{tag}[/magenta]" if tag else "→ latest on each plugin's branch"
    console.print(Panel.fit(f"📦 [bold blue]Updating {total} plugin(s)[/bold blue] {target}"))

    ok: list[str] = []
    failed: list[str] = []
    for kind, names, rebuild in (
        ("Agent", agents, agent_rebuild),
        ("Channel", channels, channel_rebuild),
    ):
        for n in names:
            console.print(f"\n[bold]{kind}[/bold] [cyan]{n}[/cyan]")
            try:
                # core_name MUST be passed explicitly: these command funcs
                # are called directly (not via Typer), so an omitted --core
                # would default to the OptionInfo sentinel, not None.
                rebuild(name=n, no_cache=False, pull=True, tag=tag, core_name=None)
                ok.append(n)
            except (typer.Exit, SystemExit, Exception) as e:  # noqa: BLE001
                # Per-plugin isolation: log and keep going. The rebuild
                # command already printed the specific error before exiting.
                if not isinstance(e, (typer.Exit, SystemExit)):
                    console.print(f"[red]{n}: {e}[/red]")
                failed.append(n)

    summary = f"\n[bold green]Rebuilt {len(ok)}/{total} plugin(s).[/bold green]"
    if failed:
        summary += f" [red]{len(failed)} failed: {', '.join(failed)}[/red]"
    console.print(summary)
    if skipped:
        console.print(f"[dim]Skipped {len(skipped)} remote agent(s) (no source to pin): {', '.join(skipped)}[/dim]")
