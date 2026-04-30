"""Operator proxies: container log tail + pass-through to the local ADK web server.

`/api/logs/{service}` shells out to `docker logs --tail`. The service name
is validated against a hard-coded prefix allow-list AND the dynamic set
of registered external-agent container names, to prevent command
injection via path parameter.

`/api/proxy/run_sse` and `/api/proxy/sessions/...` forward to the local
`adk web` instance (default port 18080) so the dashboard front-end can
hit a single CORS origin instead of cross-origin requesting the ADK
server directly.
"""
import os
import subprocess

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from services.auth import AuthManager
from services.config import ConfigManager

router = APIRouter()


@router.get("/api/logs/{service}")
def get_service_logs(service: str, tail: int = 100, auth: bool = Depends(AuthManager.verify_token)):
    conf = ConfigManager.get_config()
    ext_agents = conf.get("external_agents", {})

    # Resolve external agent config key (e.g. "costaff-agent-coding") → actual Docker container name
    # Docker Compose adds project prefix + replica suffix, so use `docker ps --filter` to find it
    actual_service = service
    if service in ext_agents:
        cnames = ext_agents[service].get("container_names", [])
        if cnames:
            ps = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={cnames[0]}", "--format", "{{.Names}}"],
                capture_output=True, text=True
            )
            matches = [n for n in ps.stdout.strip().splitlines() if cnames[0] in n]
            if matches:
                actual_service = matches[0]

    # Validate resolved name to prevent command injection
    allowed_prefixes = ("costaff", "bot-", "postgres", "gpt-vis")
    ext_containers = {c for a in ext_agents.values() for c in a.get("container_names", [])}
    if not any(actual_service.startswith(p) for p in allowed_prefixes) and actual_service not in ext_containers:
        raise HTTPException(status_code=400, detail="Invalid service name.")

    cmd = ["docker", "logs", "--tail", str(tail), actual_service]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return {"logs": res.stdout + res.stderr}


@router.post("/api/proxy/run_sse")
async def proxy_run_sse(req: dict = Body(...), auth: bool = Depends(AuthManager.verify_token)):
    async def gen():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"http://localhost:{os.getenv('COSTAFF_AGENT_PORT', '18080')}/run_sse", json=req) as r:
                async for line in r.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/api/proxy/sessions/{app_name}/{user_id}/{session_id}")
async def proxy_create_session(app_name: str, user_id: str, session_id: str, auth: bool = Depends(AuthManager.verify_token)):
    async with httpx.AsyncClient() as client:
        res = await client.post(f"http://localhost:{os.getenv('COSTAFF_AGENT_PORT', '18080')}/apps/{app_name}/users/{user_id}/sessions/{session_id}", json={"state": {}})
        return res.json()
