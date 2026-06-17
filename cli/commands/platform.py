"""`costaff platform` — manage CoStaff business platforms (ERP/CRM/HRM/…).

Platforms differ from channels/agents: each one is a SELF-CONTAINED
compose project (backend + frontend + optional MCP) with its own .env,
not a fragment merged into the core compose. The CLI therefore runs
`docker compose` inside each platform's source directory and tracks the
registration in config.json under `platforms`.

All platforms share ONE PostgreSQL instance (the `db` pseudo-platform,
repo costaff-platform-db): one role + one database per service. The CLI
owns the password plumbing — the db repo's .env is the source of truth
and each platform's .env is synced to it on `platform add`.

Start order matters and the CLI enforces it:
    db (shared Postgres) → account-manager (OIDC IdP, seeds the other
    platforms' clients) → everything else.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
from typing import List, Optional

import httpx
import questionary
import typer
from rich.console import Console
from rich.table import Table

from services.config import ConfigManager
from services.runtime.git import Git, GitError
from services.platform_ops import (
    DB_CONTAINER, DB_NETWORK,
    start_order as _start_order,
    compose as _compose,
    ensure_networks as _ensure_networks,
)
from utils.paths import _base_dir

console = Console()

platform_app = typer.Typer(help="Manage business platforms (shared-DB compose projects).")

_GH = "https://github.com/costaff-ai"

# Official CoStaff Platform Registry.
#   prefix : env-var prefix used by the platform's compose (<P>_DB_PASSWORD …)
#   oidc   : the Account Manager seeds an `AM_<oidc>_CLIENT_SECRET` client
#            for this platform (None → platform doesn't use OIDC)
#   port   : default frontend (public) port
OFFICIAL_PLATFORMS = {
    "db":              {"github": f"{_GH}/costaff-platform-db.git", "prefix": None, "oidc": None, "port": None},
    "account-manager": {"github": f"{_GH}/costaff-platform-account-manager.git", "prefix": "AM", "oidc": None, "port": 18320},
    "erp":             {"github": f"{_GH}/costaff-platform-erp.git", "prefix": "ERP", "oidc": "ERP", "port": 18210},
    "crm":             {"github": f"{_GH}/costaff-platform-crm.git", "prefix": "CRM", "oidc": "CRM", "port": 18250},
    "scm":             {"github": f"{_GH}/costaff-platform-scm.git", "prefix": "SCM", "oidc": "SCM", "port": 18310},
    "hrm":             {"github": f"{_GH}/costaff-platform-hrm.git", "prefix": "HRM", "oidc": "HRM", "port": 18410},
    "plm":             {"github": f"{_GH}/costaff-platform-plm.git", "prefix": "PLM", "oidc": "PLM", "port": 18510},
    "accounting":      {"github": f"{_GH}/costaff-platform-accounting.git", "prefix": "ACC", "oidc": None, "port": 18610},
    "knowledge":       {"github": f"{_GH}/costaff-platform-knowledge.git", "prefix": "KMS", "oidc": "KMS", "port": 18710},
    "project":         {"github": f"{_GH}/costaff-platform-project.git", "prefix": "PROJECT", "oidc": "PROJECT", "port": 18730},
    "expense":         {"github": f"{_GH}/costaff-platform-expense.git", "prefix": "EXPENSE", "oidc": "EXPENSE", "port": 18750},
    "helpdesk":        {"github": f"{_GH}/costaff-platform-helpdesk.git", "prefix": "HELPDESK", "oidc": "HELPDESK", "port": 18770},
}

# Keys whose empty values get a random secret on env bootstrap.
_SECRET_KEY_RE = re.compile(r"_(PASSWORD|SECRET|KEY|SALT)$")


# --------------------------------------------------------------------------
# env-file helpers (compose-style KEY=VALUE files, comments preserved)
# --------------------------------------------------------------------------


def _read_env_value(path: str, key: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    for line in open(path):
        line = line.strip()
        if line.startswith(f"{key}="):
            return line[len(key) + 1:]
    return None


def _set_env_value(path: str, key: str, value: str) -> None:
    """Set KEY=value, replacing an existing assignment or appending."""
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _fill_env_secrets(path: str) -> List[str]:
    """Fill every empty *_PASSWORD/_SECRET/_KEY/_SALT with a random value.

    Mirrors each platform repo's `make init-secrets` so `platform add`
    doesn't depend on make. Returns the keys that were filled."""
    filled: List[str] = []
    lines = open(path).read().splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z0-9_]+)=\s*$", line)
        if m and _SECRET_KEY_RE.search(m.group(1)):
            lines[i] = f"{m.group(1)}={secrets.token_urlsafe(24)}"
            filled.append(m.group(1))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return filled


def _ensure_env_file(src: str) -> str:
    """Create .env from .env.example when missing. Returns the .env path."""
    env_path = os.path.join(src, ".env")
    if not os.path.exists(env_path):
        example = os.path.join(src, ".env.example")
        if not os.path.exists(example):
            raise FileNotFoundError(f".env.example not found in {src}")
        shutil.copy(example, env_path)
    return env_path


# --------------------------------------------------------------------------
# secret plumbing between repos
# --------------------------------------------------------------------------


def _sync_db_password(prefix: str, platform_env: str, db_env: str) -> str:
    """Make <prefix>_DB_PASSWORD identical in the platform's .env and the
    shared db repo's .env. The db side wins when both are set; a single
    random value is generated when neither is."""
    key = f"{prefix}_DB_PASSWORD"
    db_val = (_read_env_value(db_env, key) or "").strip()
    pf_val = (_read_env_value(platform_env, key) or "").strip()
    value = db_val or pf_val or secrets.token_urlsafe(24)
    if db_val != value:
        _set_env_value(db_env, key, value)
    if pf_val != value:
        _set_env_value(platform_env, key, value)
    return value


def _sync_oidc_secret(oidc: str, prefix: str, platform_env: str, am_env: Optional[str]) -> Optional[str]:
    """Make <prefix>_OIDC_CLIENT_SECRET (platform side) equal to
    AM_<oidc>_CLIENT_SECRET (Account Manager side).

    Either side may already hold a value (AM wins on conflict); when both
    are empty one is generated. Returns the value, or None when the AM
    isn't installed yet (platform side still gets a value so its compose
    can boot; re-run `platform add account-manager` to sync)."""
    pf_key = f"{prefix}_OIDC_CLIENT_SECRET"
    am_key = f"AM_{oidc}_CLIENT_SECRET"
    am_val = (_read_env_value(am_env, am_key) or "").strip() if am_env else ""
    pf_val = (_read_env_value(platform_env, pf_key) or "").strip()
    value = am_val or pf_val or secrets.token_urlsafe(32)
    if pf_val != value:
        _set_env_value(platform_env, pf_key, value)
    if am_env and am_val != value:
        _set_env_value(am_env, am_key, value)
    return value if am_env else None


# --------------------------------------------------------------------------
# compose plumbing  (_start_order / _compose / _ensure_networks live in
# services.platform_ops so the dashboard router can reuse them)
# --------------------------------------------------------------------------


def _platform_src(name: str) -> str:
    return os.path.join(_base_dir, "costaff-platform", name, "src")


def _container_names(src: str) -> List[str]:
    import yaml

    compose = os.path.join(src, "docker-compose.yaml")
    with open(compose) as f:
        doc = yaml.safe_load(f)
    return [
        s.get("container_name", svc)
        for svc, s in (doc.get("services") or {}).items()
        if isinstance(s, dict)
    ]


def _frontend_port(src: str, name: str) -> Optional[int]:
    """Default frontend port from the compose text, falling back to the
    official registry."""
    compose = os.path.join(src, "docker-compose.yaml")
    if os.path.exists(compose):
        m = re.search(r"\$\{[A-Z0-9_]*FRONTEND_PORT:-(\d+)\}", open(compose).read())
        if m:
            return int(m.group(1))
    return (OFFICIAL_PLATFORMS.get(name) or {}).get("port")


def _db_entry(conf: dict) -> Optional[dict]:
    return conf.get("platforms", {}).get("db")


def _provision_db(db_src: str) -> None:
    """Recreate the db container if its env changed, then re-run the
    idempotent role/database provisioning script inside it."""
    _compose(db_src, "up", "-d")
    _compose(
        db_src, "exec", "-T", DB_CONTAINER,
        "sh", "/docker-entrypoint-initdb.d/01-create-services.sh",
    )


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


@platform_app.command("add")
def platform_add(
    name: str = typer.Argument(..., help="Platform name (e.g. erp, crm, account-manager, db)"),
    local: Optional[str] = typer.Option(None, "--local", help="Local project path (skip clone)"),
    github: Optional[str] = typer.Option(None, "--github", help="GitHub repository URL"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin clone to a tag / branch / commit"),
    start: bool = typer.Option(True, "--start/--no-start", help="Start containers after registering"),
):
    """Add a business platform (clones, wires the shared DB + OIDC secrets, starts)."""
    name = name.strip().lower()

    if not local and not github:
        if name in OFFICIAL_PLATFORMS:
            github = OFFICIAL_PLATFORMS[name]["github"]
            console.print(f"📦 [bold cyan]{name}[/bold cyan] recognized as an official platform.")
        else:
            console.print(f"[red]Error: '{name}' is not an official platform. Provide --github or --local.[/red]")
            raise typer.Exit(1)

    conf = ConfigManager.get_config()
    conf.setdefault("platforms", {})
    if name in conf["platforms"]:
        console.print(f"[red]Error: Platform '{name}' already exists.[/red]")
        raise typer.Exit(1)

    # --- source ---
    if github:
        src = _platform_src(name)
        if os.path.exists(src):
            if not questionary.confirm(f"Source directory {src} already exists. Overwrite?").ask():
                raise typer.Exit(0)
            shutil.rmtree(src)
        os.makedirs(os.path.dirname(src), exist_ok=True)
        console.print(f"Cloning [bold cyan]{github}[/bold cyan]{f' @ {tag}' if tag else ''}...")
        try:
            Git().clone(github, src, ref=tag, depth=0 if tag else 1)
        except GitError as e:
            console.print(f"[red]Git clone failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        src = os.path.abspath(local)

    if not os.path.exists(os.path.join(src, "docker-compose.yaml")):
        console.print(f"[red]Error: docker-compose.yaml not found in {src}.[/red]")
        raise typer.Exit(1)

    meta = OFFICIAL_PLATFORMS.get(name, {})
    prefix = meta.get("prefix")
    _ensure_networks()

    # --- the shared DB itself ---
    if name == "db":
        env_path = _ensure_env_file(src)
        filled = _fill_env_secrets(env_path)
        if filled:
            console.print(f"Generated secrets: [dim]{', '.join(filled)}[/dim]")
        if start:
            _compose(src, "up", "-d")
        conf["platforms"]["db"] = _registry_entry(src, github, tag, public_port=None)
        ConfigManager.save_config(conf)
        console.print("[green]Shared platform DB registered and started.[/green]")
        return

    # --- ordinary platform: needs the shared DB first ---
    db = _db_entry(conf)
    if not db:
        console.print("[yellow]Shared platform DB not installed — adding it first…[/yellow]")
        platform_add("db", local=None, github=None, tag=None, start=True)
        conf = ConfigManager.get_config()
        conf.setdefault("platforms", {})
        db = _db_entry(conf)

    env_path = _ensure_env_file(src)
    db_env = os.path.join(db["source_path"], ".env")

    if prefix:
        _sync_db_password(prefix, env_path, db_env)

    oidc = meta.get("oidc")
    if oidc and prefix:
        am = conf["platforms"].get("account-manager")
        am_env = os.path.join(am["source_path"], ".env") if am else None
        synced = _sync_oidc_secret(oidc, prefix, env_path, am_env)
        if synced is None:
            console.print(
                "[yellow]Account Manager not installed — OIDC client secret generated "
                "locally; add account-manager to sync it into the IdP.[/yellow]"
            )

    # AM installed AFTER other platforms: pull their secrets into its .env
    if name == "account-manager":
        for other, info in conf["platforms"].items():
            o_meta = OFFICIAL_PLATFORMS.get(other, {})
            if o_meta.get("oidc") and o_meta.get("prefix"):
                other_env = os.path.join(info["source_path"], ".env")
                if os.path.exists(other_env):
                    _sync_oidc_secret(o_meta["oidc"], o_meta["prefix"], other_env, env_path)

    filled = _fill_env_secrets(env_path)
    if filled:
        console.print(f"Generated secrets: [dim]{', '.join(filled)}[/dim]")

    console.print("Provisioning shared-DB role/database…")
    try:
        _provision_db(db["source_path"])
    except subprocess.CalledProcessError:
        console.print("[yellow]DB provisioning failed — run `costaff platform provision` once the DB is up.[/yellow]")

    if start:
        console.print(f"Building and starting platform [bold]{name}[/bold]…")
        _compose(src, "up", "-d", "--build")

    public_port = _frontend_port(src, name)
    conf["platforms"][name] = _registry_entry(src, github, tag, public_port=public_port)
    ConfigManager.save_config(conf)
    console.print(f"[green]Platform '{name}' deployed and registered"
                  + (f" — UI on http://localhost:{public_port}[/green]" if public_port else ".[/green]"))


def _registry_entry(src: str, github: Optional[str], tag: Optional[str], public_port: Optional[int]) -> dict:
    entry = {
        "type": "github" if github else "local",
        "source_path": src,
        "compose_path": os.path.join(src, "docker-compose.yaml"),
        "public_port": public_port,
        "enabled": True,
        "container_names": _container_names(src),
    }
    if tag:
        entry["ref"] = tag
    return entry


@platform_app.command("list")
def platform_list():
    """List registered platforms (with frontend health check)."""
    conf = ConfigManager.get_config()
    platforms = conf.get("platforms", {})
    if not platforms:
        console.print("[yellow]No platforms configured.[/yellow]")
        return
    table = Table(title="Business Platforms")
    table.add_column("Name", style="cyan")
    table.add_column("Ref", style="magenta")
    table.add_column("Port", justify="center")
    table.add_column("Health", justify="center")
    table.add_column("Enabled", justify="center")
    for name in _start_order(platforms):
        info = platforms[name]
        port = info.get("public_port")
        health = "—"
        if port and info.get("enabled"):
            try:
                r = httpx.get(f"http://localhost:{port}/", timeout=3.0, follow_redirects=True)
                health = "[green]●[/green]" if r.status_code < 500 else "[red]●[/red]"
            except Exception:
                health = "[red]●[/red]"
        table.add_row(
            name, info.get("ref") or "—", str(port) if port else "N/A",
            health, "✓" if info.get("enabled") else "✗",
        )
    console.print(table)


@platform_app.command("remove")
def platform_remove(
    name: str = typer.Argument(...),
    purge: bool = typer.Option(False, "--purge", help="Also remove the platform's data volumes"),
):
    """Stop and deregister a platform (volumes survive unless --purge)."""
    conf = ConfigManager.get_config()
    if name not in conf.get("platforms", {}):
        console.print(f"[red]Error: Platform '{name}' not found.[/red]")
        raise typer.Exit(1)
    if name == "db":
        others = [n for n in conf["platforms"] if n != "db"]
        if others:
            console.print(f"[red]Error: other platforms still depend on the shared DB: {', '.join(others)}.[/red]")
            raise typer.Exit(1)
    if not questionary.confirm(f"Remove platform '{name}'{' AND its volumes' if purge else ''}?").ask():
        return

    src = conf["platforms"][name]["source_path"]
    args = ["down", "-v"] if purge else ["down"]
    try:
        _compose(src, *args)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[yellow]compose down failed ({e}) — deregistering anyway.[/yellow]")

    del conf["platforms"][name]
    ConfigManager.save_config(conf)
    console.print(f"[green]Platform '{name}' removed.[/green]")


@platform_app.command("restart")
def platform_restart(name: str = typer.Argument(...)):
    """Restart a platform's containers."""
    conf = ConfigManager.get_config()
    if name not in conf.get("platforms", {}):
        console.print(f"[red]Error: Platform '{name}' not found.[/red]")
        raise typer.Exit(1)
    _compose(conf["platforms"][name]["source_path"], "restart")
    console.print(f"[green]Platform '{name}' restarted.[/green]")


@platform_app.command("rebuild")
def platform_rebuild(
    name: str = typer.Argument(...),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="Sync source from origin before rebuilding"),
    tag: Optional[str] = typer.Option(None, "--tag", "--ref", help="Pin to a different tag / branch / commit"),
):
    """Rebuild images and restart a platform from source."""
    conf = ConfigManager.get_config()
    if name not in conf.get("platforms", {}):
        console.print(f"[red]Error: Platform '{name}' not found.[/red]")
        raise typer.Exit(1)
    entry = conf["platforms"][name]
    src = entry["source_path"]

    effective_ref = tag or entry.get("ref")
    git = Git()
    ref_sync_ok = False
    if pull and git.is_repo(src):
        if effective_ref:
            console.print(f"Syncing [bold]{name}[/bold] to [bold cyan]{effective_ref}[/bold cyan]…")
            try:
                git.fetch_tags(src)
                git.checkout(src, effective_ref)
                ref_sync_ok = True
            except GitError as e:
                console.print(f"[yellow]Ref sync failed ({e}); rebuilding current source.[/yellow]")
        else:
            try:
                git.pull_ff_only(src)
            except GitError as e:
                console.print(f"[yellow]Pull failed ({e}); rebuilding current source.[/yellow]")

    if tag and tag != entry.get("ref") and ref_sync_ok:
        entry["ref"] = tag
        ConfigManager.save_config(conf)

    build_args = ["build"] + (["--no-cache"] if no_cache else [])
    try:
        _compose(src, *build_args)
        _compose(src, "up", "-d", "--force-recreate")
    except subprocess.CalledProcessError:
        console.print(f"[red]Rebuild failed for platform '{name}'.[/red]")
        raise typer.Exit(1)
    entry["container_names"] = _container_names(src)
    ConfigManager.save_config(conf)
    console.print(f"[green]Platform '{name}' rebuilt and restarted.[/green]")


@platform_app.command("start")
def platform_start(build: bool = typer.Option(False, "--build", help="Rebuild images while starting")):
    """Start ALL enabled platforms in dependency order (db → IdP → rest)."""
    conf = ConfigManager.get_config()
    platforms = conf.get("platforms", {})
    if not platforms:
        console.print("[yellow]No platforms configured.[/yellow]")
        return
    _ensure_networks()
    for name in _start_order(platforms):
        info = platforms[name]
        if not info.get("enabled"):
            continue
        console.print(f"🚀 Starting platform [bold]{name}[/bold]…")
        args = ["up", "-d"] + (["--build"] if build else [])
        try:
            _compose(info["source_path"], *args)
        except subprocess.CalledProcessError:
            console.print(f"[red]Failed to start platform '{name}' — continuing with the rest.[/red]")
    console.print("[bold green]Platforms started (db → account-manager → others).[/bold green]")


@platform_app.command("stop")
def platform_stop():
    """Stop ALL platforms (reverse dependency order; volumes survive)."""
    conf = ConfigManager.get_config()
    platforms = conf.get("platforms", {})
    for name in reversed(_start_order(platforms)):
        console.print(f"Stopping platform [bold]{name}[/bold]…")
        try:
            _compose(platforms[name]["source_path"], "down")
        except subprocess.CalledProcessError:
            console.print(f"[yellow]compose down failed for '{name}'.[/yellow]")


@platform_app.command("provision")
def platform_provision():
    """Re-run the shared DB's idempotent role/database provisioning."""
    conf = ConfigManager.get_config()
    db = _db_entry(conf)
    if not db:
        console.print("[red]Error: shared platform DB not installed (costaff platform add db).[/red]")
        raise typer.Exit(1)
    _provision_db(db["source_path"])
    console.print("[green]Provisioning complete.[/green]")
