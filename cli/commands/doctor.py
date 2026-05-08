import json
import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from services.config import ConfigManager
from services.docker import DockerManager
from utils.paths import PATHS, _project_root, _runtime_root


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _print_logs(console: Console, output: str):
    if not output.strip():
        console.print("[dim](no output)[/dim]")
        return
    for line in output.splitlines():
        low = line.lower()
        if any(kw in low for kw in ["error", "fail", "exception", "traceback",
                                     " 401", " 403", " 500", " 502", " 503"]):
            console.print(f"[red]{line}[/red]")
        elif any(kw in low for kw in ["warn", "warning"]):
            console.print(f"[yellow]{line}[/yellow]")
        else:
            console.print(line)


def _mcp_healthcheck(console: Console, mcp_secret: str):
    """Probe MCP endpoint from inside the agent container (MCP is not host-exposed)."""
    # FastMCP streamable-http typically expects POST.
    # We use a minimal python script that catches HTTPErrors to print the code.
    probe_script = (
        "import urllib.request,urllib.error\n"
        "def probe(url, auth=None):\n"
        "    try:\n"
        "        headers = {'Accept': 'application/json'}\n"
        "        if auth: headers['Authorization'] = f'Bearer {auth}'\n"
        "        req = urllib.request.Request(url, data=b'{}', headers=headers, method='POST')\n"
        "        with urllib.request.urlopen(req, timeout=5) as r: print(r.status)\n"
        "    except urllib.error.HTTPError as e: print(e.code)\n"
        "    except Exception as e: print(f'ERR:{e}')\n"
    )

    # 1. Unauthenticated probe (expected 401)
    cmd_unauth = probe_script + "probe('http://costaff-mcp-costaff:8081/mcp')\n"
    r = _run(["docker", "exec", "costaff-agent-costaff", "python3", "-c", cmd_unauth])
    code = (r.stdout or r.stderr).strip()
    if code == "401":
        console.print(f"[green]✔[/green] MCP /mcp unauth → {code} (expected 401)")
    else:
        console.print(f"[yellow]⚠[/yellow] MCP /mcp unauth → {code} (expected 401)")

    # 2. Authenticated probe
    if not mcp_secret:
        console.print("[yellow]MCP_SECRET_KEY not set — skipping authenticated probe[/yellow]")
        return

    cmd_auth = probe_script + f"probe('http://costaff-mcp-costaff:8081/mcp', '{mcp_secret}')\n"
    r = _run(["docker", "exec", "costaff-agent-costaff", "python3", "-c", cmd_auth])
    code = (r.stdout or r.stderr).strip()
    
    # Any 2xx or 4xx (like 400 Bad Request) indicates the server is alive and talking
    if code.isdigit() and int(code) < 500:
        console.print(f"[green]✔[/green] MCP /mcp Bearer → {code}")
    else:
        console.print(f"[red]✖[/red] MCP /mcp Bearer → {code}")


def doctor():
    """Diagnose CoStaff services and report issues. Saves a timestamped log file."""
    console = Console(record=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    console.print(Panel.fit(f"[bold blue]CoStaff Doctor[/bold blue]", subtitle=f"{ts}"))

    # 0. Version / git rev ─────────────────────────────────────────────────────
    console.print("\n[bold]0. Version[/bold]")
    try:
        from utils.paths import VERSION
        console.print(f"costaff: {VERSION}")
    except Exception:
        pass
    try:
        rev = _run(["git", "rev-parse", "--short", "HEAD"], cwd=_project_root).stdout.strip()
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_project_root).stdout.strip()
        status = _run(["git", "status", "--porcelain"], cwd=_project_root).stdout.strip()
        dirty = "dirty" if status else "clean"
        console.print(f"git: {branch} @ {rev} ({dirty})")
        if status:
            for line in status.splitlines()[:10]:
                console.print(f"  [yellow]{line}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]git info unavailable: {e}[/yellow]")

    # 1. Containers with image build time ──────────────────────────────────────
    console.print("\n[bold]1. Containers[/bold]")
    compose_cwd = DockerManager.get_compose_cwd("docker-compose.yaml")
    r = _run(DockerManager.get_cmd() + ["-f", "docker-compose.yaml", "ps",
                                        "--format", "json", "-a"], cwd=compose_cwd)
    if r.returncode == 0 and r.stdout.strip():
        t = Table("container", "state", "image", "built")
        for line in r.stdout.strip().splitlines():
            try:
                c = json.loads(line)
            except Exception:
                continue
            name = c.get("Name", "")
            state = f'{c.get("State", "")} ({c.get("Status", "")})'
            image = c.get("Image", "")
            built = ""
            if image:
                insp = _run(["docker", "image", "inspect", image,
                             "--format", "{{.Created}}"])
                built = insp.stdout.strip()[:19].replace("T", " ")
            t.add_row(name, state, image, built)
        console.print(t)
    else:
        console.print(f"[red]docker compose ps failed:[/red] {r.stderr.strip()}")

    # 2. Docker network ────────────────────────────────────────────────────────
    console.print("\n[bold]2. Network[/bold]")
    r = _run(["docker", "network", "ls", "--filter", "name=costaff_default",
              "--format", "{{.Name}}"])
    if "costaff_default" in r.stdout:
        console.print("[green]✔[/green] costaff_default exists")
    else:
        console.print("[red]✖[/red] costaff_default not found — run 'costaff start'")

    # 3. HTTP healthcheck ──────────────────────────────────────────────────────
    console.print("\n[bold]3. HTTP Healthcheck[/bold]")
    from dotenv import dotenv_values
    env = dotenv_values(PATHS["env"])
    agent_port = env.get("COSTAFF_AGENT_PORT", "18080").strip("'\"")
    mcp_secret = env.get("MCP_SECRET_KEY", "").strip("'\"")
    try:
        import httpx
        r = httpx.get(f"http://localhost:{agent_port}/", timeout=5.0,
                      follow_redirects=True)
        color = "green" if r.status_code < 500 else "red"
        console.print(f"[{color}]Agent http://localhost:{agent_port}/ → {r.status_code}[/{color}]")
    except Exception as e:
        console.print(f"[red]✖[/red] Agent port {agent_port} unreachable: {e}")

    _mcp_healthcheck(console, mcp_secret)

    # 4. .env variables ────────────────────────────────────────────────────────
    console.print("\n[bold]4. .env Variables[/bold]")
    keys = [
        "COSTAFF_AGENT_MODEL_PROVIDER", "COSTAFF_AGENT_GEMINI_MODEL",
        "COSTAFF_PREFERRED_LANGUAGE", "ADK_SESSION_SERVICE_URI",
        "GOOGLE_API_KEY", "MCP_SECRET_KEY", "API_HEADERS_KEY",
    ]
    t = Table("key", "value")
    for k in keys:
        v = env.get(k, "").strip("'\"")
        if not v:
            masked = "(not set)"
        elif "KEY" in k or "SECRET" in k or "URI" in k:
            masked = (v[:4] + "****") if len(v) > 4 else "****"
        else:
            masked = v
        t.add_row(k, masked)
    console.print(t)

    # MCP_SERVER_URLS structure
    mcp_raw = env.get("MCP_SERVER_URLS", "").strip("'\"")
    if mcp_raw:
        try:
            parsed = json.loads(mcp_raw)
            t2 = Table("mcp", "url", "transport", "bearer")
            for n, v in parsed.items():
                if isinstance(v, str):
                    t2.add_row(n, v, "(inferred)", "")
                else:
                    auth = v.get("headers", {}).get("Authorization", "")
                    bearer = "✔" if auth.lower().startswith("bearer ") else ""
                    t2.add_row(n, v.get("url", ""), v.get("transport", ""), bearer)
            console.print(t2)
        except json.JSONDecodeError as e:
            console.print(f"[red]MCP_SERVER_URLS not valid JSON:[/red] {e}")

    # 5. config.json summary ───────────────────────────────────────────────────
    console.print("\n[bold]5. config.json[/bold]")
    conf = ConfigManager.get_config()
    channels = conf.get("dynamic_channels", {})
    ext_agents = conf.get("external_agents", {})
    console.print(f"channels: {len(channels)} — {', '.join(channels.keys()) or '(none)'}")
    console.print(f"external_agents: {len(ext_agents)} — {', '.join(ext_agents.keys()) or '(none)'}")
    console.print(f"mcp: {conf.get('mcp', [])}")
    # Fragment path existence
    for name, entry in channels.items():
        frag = entry.get("fragment_path", "")
        src = entry.get("source_path", "")
        if frag and not Path(frag).exists():
            console.print(f"  [red]✖[/red] {name}: fragment missing at {frag}")
        if src and not Path(src).exists():
            console.print(f"  [red]✖[/red] {name}: source missing at {src}")

    # 6. identity_maps ─────────────────────────────────────────────────────────
    console.print("\n[bold]6. identity_maps (last 10 rows)[/bold]")
    try:
        from sqlalchemy import create_engine, text
        db_uri = env.get("ADK_SESSION_SERVICE_URI", "").strip("'\"")
        if db_uri:
            sync_uri = (db_uri
                        .replace("postgresql+asyncpg://", "postgresql://")
                        .replace("@postgres:", "@localhost:"))
            engine = create_engine(sync_uri, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                rows = list(conn.execute(text(
                    "SELECT session_id, real_id, is_approved, created_at "
                    "FROM identity_maps ORDER BY created_at DESC LIMIT 10"
                )))
                if rows:
                    t3 = Table("session_id", "real_id", "approved", "created_at")
                    for row in rows:
                        t3.add_row(str(row[0]), str(row[1]), str(row[2]), str(row[3]))
                    console.print(t3)
                else:
                    console.print("[yellow](empty — sync_identity may have failed)[/yellow]")
        else:
            console.print("[yellow]ADK_SESSION_SERVICE_URI not set[/yellow]")
    except Exception as e:
        console.print(f"[red]DB error:[/red] {e}")

    # 7. Core container logs (agent + mcp) ────────────────────────────────────
    console.print("\n[bold]7. Core Logs (last 50 lines)[/bold]")
    for cname in ["costaff-agent-costaff", "costaff-mcp-costaff"]:
        console.print(f"\n[cyan]── {cname} ──[/cyan]")
        r = _run(["docker", "logs", "--tail", "50", cname])
        _print_logs(console, r.stdout + r.stderr)

    # 8. Channel logs ──────────────────────────────────────────────────────────
    console.print("\n[bold]8. Channel Logs (last 40 lines)[/bold]")
    if not channels:
        console.print("[yellow](no channels configured)[/yellow]")
    else:
        for name, entry in channels.items():
            for cname in entry.get("container_names", []):
                console.print(f"\n[cyan]── {cname} (channel {name}) ──[/cyan]")
                r = _run(["docker", "logs", "--tail", "40", cname])
                _print_logs(console, r.stdout + r.stderr)

    # Save log file ────────────────────────────────────────────────────────────
    log_dir = Path(_runtime_root) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"doctor_{ts}.log"
    try:
        console.save_text(str(log_path), clear=False)
        console.print(f"\n[bold green]Doctor complete.[/bold green] Log → [cyan]{log_path}[/cyan]")
    except Exception as e:
        console.print(f"[yellow]Could not save log file: {e}[/yellow]")
