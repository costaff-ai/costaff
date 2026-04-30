import json
from typing import Optional

import httpx

from core import models
from core.database import SessionLocal
from mcp_servers.core import mcp
from mcp_servers.utils import _decrypt_headers, _is_safe_url


def _get_accessible_api_configs(db, user_id: str, agent_id: str = "__all__"):
    all_configs = db.query(models.ApiConfig).filter(models.ApiConfig.is_active == True).all()
    result = []
    for c in all_configs:
        if not any(uid.strip() in (user_id, "__global__") for uid in c.user_id.split(',')):
            continue
        a_ids = c.agent_ids or "__all__"
        if agent_id == "__all__" or a_ids == "__all__" or any(aid.strip() in (agent_id, "__all__") for aid in a_ids.split(',')):
            result.append(c)
    return result


@mcp.tool()
async def get_apis(user_id: str, agent_id: str = "__all__") -> str:
    """Returns a brief index of all active external APIs available to this user and agent."""
    db = SessionLocal()
    try:
        configs = _get_accessible_api_configs(db, user_id, agent_id)
        if not configs:
            return "No external APIs registered for this user."
        return json.dumps([{"name": c.name, "description": c.description or ""} for c in configs], ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
async def search_api(user_id: str, query: str, agent_id: str = "__all__") -> str:
    """Searches available APIs by matching the query against name and description."""
    db = SessionLocal()
    try:
        configs = _get_accessible_api_configs(db, user_id, agent_id)
        q = query.lower()
        matched = [c for c in configs if q in (c.name or "").lower() or q in (c.description or "").lower()]
        if not matched:
            return f"No APIs found matching '{query}'."
        return json.dumps([{"name": c.name, "method": c.method, "description": c.description or ""} for c in matched], ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
async def get_api_detail(user_id: str, api_name: str, agent_id: str = "__all__") -> str:
    """Returns full detail of a specific API including URL and auth header key names."""
    db = SessionLocal()
    try:
        configs = _get_accessible_api_configs(db, user_id, agent_id)
        config = next((c for c in configs if c.name == api_name), None)
        if not config:
            return f"API '{api_name}' not found."
        header_keys = []
        if config.headers_encrypted:
            try:
                header_keys = list(_decrypt_headers(config.headers_encrypted).keys())
            except Exception:
                pass
        return json.dumps({
            "name": config.name, "method": config.method, "url": config.url,
            "description": config.description or "", "auth_header_keys": header_keys
        }, ensure_ascii=False, indent=2)
    finally:
        db.close()


@mcp.tool()
async def request_api(user_id: str, api_name: str, agent_id: str = "__all__", params: Optional[dict] = None, body: Optional[dict] = None) -> str:
    """Executes an HTTP request to a user-registered external API."""
    db = SessionLocal()
    try:
        all_candidates = db.query(models.ApiConfig).filter(
            models.ApiConfig.name == api_name, models.ApiConfig.is_active == True
        ).all()
        config = next((
            c for c in all_candidates
            if any(uid.strip() in (user_id, "__global__") for uid in c.user_id.split(','))
            and (not c.agent_ids or c.agent_ids == "__all__" or agent_id == "__all__"
                 or any(aid.strip() in (agent_id, "__all__") for aid in c.agent_ids.split(',')))
        ), None)
        if not config:
            return f"Error: API '{api_name}' not found or access denied."
        if not _is_safe_url(config.url):
            return "Error: API URL resolved to a restricted address."
        headers = _decrypt_headers(config.headers_encrypted) if config.headers_encrypted else {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method=config.method, url=config.url, headers=headers,
                params=params or {}, json=body if body else None
            )
        body_text = response.text[:8000]
        truncated = " [TRUNCATED]" if len(response.text) > 8000 else ""
        return f"[EXTERNAL_DATA_START]\nStatus: {response.status_code}\n{body_text}{truncated}\n[EXTERNAL_DATA_END]"
    except httpx.TimeoutException:
        return "Error: Request timed out."
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()
