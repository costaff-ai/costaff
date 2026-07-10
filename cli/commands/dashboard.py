import json
import os
import secrets
import threading
import time
import webbrowser

import httpx
import questionary
import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console

from server.app import server
from utils.paths import PATHS

console = Console()


def _agent_base() -> str:
    port = os.getenv("COSTAFF_AGENT_PORT", "18080")
    return f"http://localhost:{port}"


def dashboard(
    port: int = 8501,
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="Interface to bind. Localhost-only by default: before the admin "
        "account exists, /api/setup is open to whoever reaches it first. "
        "Pass --host 0.0.0.0 to expose on the network (firewall/tunnel it).",
    ),
):
    """Launch the Web Dashboard."""
    load_dotenv(PATHS["env"], override=False)
    console.print(f"Launching Dashboard at http://localhost:{port}...")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{port}")), daemon=True).start()
    uvicorn.run(server, host=host, port=port, log_level="error")


def chat(app_name: str = "costaff_agent"):
    """Interactive CLI Chat with sub-agent activity logging."""
    load_dotenv(PATHS["env"], override=False)
    uid = "cli_tester_888"
    sid = f"chat_{secrets.token_hex(3)}"

    console.print(f"💬 [bold cyan]CoStaff CLI Chat[/bold cyan] (App: {app_name}, Session: {sid})")

    # 1. Ensure Session
    try:
        httpx.post(f"{_agent_base()}/apps/{app_name}/users/{uid}/sessions",
                   json={"sessionId": sid, "state": {}}, timeout=5.0)
    except Exception as e:
        console.print(f"[red]Failed to connect to agent: {e}[/red]")
        return

    while True:
        prompt = questionary.text("User:").ask()
        if not prompt or prompt.lower() in ["exit", "quit", "q"]:
            break

        _run_request(app_name, uid, sid, prompt)


def invoke(prompt: str = typer.Argument(..., help="The message to send"),
           app_name: str = typer.Option("costaff_agent", "--app")):
    """Quickly send a single message to the agent and see the response (plus sub-agent logs)."""
    load_dotenv(PATHS["env"], override=False)
    uid = "cli_tester_888"
    sid = f"invoke_{secrets.token_hex(3)}"

    # 1. Ensure Session
    try:
        httpx.post(f"{_agent_base()}/apps/{app_name}/users/{uid}/sessions",
                   json={"sessionId": sid, "state": {}}, timeout=5.0)
    except Exception:
        pass

    _run_request(app_name, uid, sid, prompt)


def _run_request(app_name, uid, sid, prompt):
    """Helper to stream response and show activity."""
    url = f"{_agent_base()}/run"
    payload = {
        "appName": app_name,
        "userId": uid,
        "sessionId": sid,
        "newMessage": {"role": "user", "parts": [{"text": f"(Context ID: {uid}) {prompt}"}]}
    }

    try:
        console.print("[dim]Thinking...[/dim]")
        with httpx.Client(timeout=None) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                console.print(f"[red]Error {resp.status_code}: {resp.text}[/red]")
                return

            events = resp.json()
            for ev in events:
                author = ev.get("author", "unknown")
                content = ev.get("content", {})
                parts = content.get("parts", [])

                # Filter out boring internal initialization
                if any(p.get("functionCall", {}).get("name") == "get_apis" for p in parts):
                    continue

                # Show A2A Delegation
                if "transferToAgent" in ev.get("actions", {}):
                    target = ev["actions"]["transferToAgent"]
                    console.print(f"📢 [bold yellow]>>> Delegating to: {target}[/bold yellow]")

                # Show Tool Calls
                for p in parts:
                    if "functionCall" in p:
                        fn = p["functionCall"]
                        console.print(f"🛠  [dim]Calling Tool: {fn['name']}({fn.get('args', {})})[/dim]")
                    if "functionResponse" in p:
                        # console.print(f"✅ [dim]Tool returned result.[/dim]")
                        pass
                    if "text" in p:
                        color = "green" if author != "user" else "white"
                        role_label = f"[bold {color}]{author.upper()}[/bold {color}]: "
                        console.print(f"{role_label}{p['text']}")
    except Exception as e:
        console.print(f"[red]Request failed: {e}[/red]")
