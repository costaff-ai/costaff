import json
import secrets
import threading
import time
import webbrowser

import httpx
import questionary
import typer
import uvicorn
from rich.console import Console

from server.app import server

console = Console()


def dashboard(port: int = 8501):
    """Launch the Web Dashboard."""
    console.print(f"Launching Dashboard at http://localhost:{port}...")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{port}")), daemon=True).start()
    uvicorn.run(server, host="0.0.0.0", port=port, log_level="error")


def chat(app_name: str = "costaff_agent"):
    """Interactive CLI Chat with sub-agent activity logging."""
    from dotenv import dotenv_values
    from utils.helpers import PATHS
    env = dotenv_values(PATHS["env"])
    
    # Try to find a real user_id from DB or fallback
    uid = "cli_tester_888"
    sid = f"chat_{secrets.token_hex(3)}"
    
    console.print(f"💬 [bold cyan]CoStaff CLI Chat[/bold cyan] (App: {app_name}, Session: {sid})")
    
    # 1. Ensure Session
    try:
        httpx.post(f"http://localhost:18080/apps/{app_name}/users/{uid}/sessions", 
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
    uid = "cli_tester_888"
    sid = f"invoke_{secrets.token_hex(3)}"
    
    # 1. Ensure Session
    try:
        httpx.post(f"http://localhost:18080/apps/{app_name}/users/{uid}/sessions", 
                   json={"sessionId": sid, "state": {}}, timeout=5.0)
    except Exception:
        pass # Might already exist
        
    _run_request(app_name, uid, sid, prompt)


def _run_request(app_name, uid, sid, prompt):
    """Helper to stream response and show activity."""
    url = "http://localhost:18080/run"
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
