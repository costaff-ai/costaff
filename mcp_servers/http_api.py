"""Plain-HTTP shim for the shared cross-agent tools.

External plugin agents (BA, Coding, Twinkle, …) need a handful of
manager-core tools: `send_message_now`, `add_task_comment`,
`move_to_shared`, `list_data_files`. Reaching them over the MCP
streamable-http transport makes each plugin open a second MCP
`ClientSession`, which triggers the anyio `CancelScope` cross-task race
(`unhandled errors in a TaskGroup`) and silently strips the plugin of
its tools.

This module exposes those four functions as ordinary JSON HTTP endpoints
on the SAME Starlette app the MCP server already serves, so a plugin can
call them with a plain `httpx.post` (no MCP client, no anyio cancel
scope, no race). The functions run in THIS process — DB, notifiers and
bot tokens stay centralised in the MCP container; nothing is duplicated
into plugin containers.

Route: POST /api/tool/{name}
  - body: JSON object of keyword arguments for the tool
  - auth: same Bearer token as the MCP endpoint (applied by the
    BearerMiddleware that wraps the whole app in server.py)
  - response: {"result": "<tool return string>"} or
              {"error": "<message>"} with HTTP 4xx/5xx
"""
import inspect
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_servers.tools.workspace import move_to_shared, list_data_files
from mcp_servers.tools.task_comments import add_task_comment
from mcp_servers.tools.messaging import send_message_now

logger = logging.getLogger("costaff-agent-engine")

# Explicit allowlist — only these four are exposed over plain HTTP.
# Everything else stays MCP-only.
_TOOL_REGISTRY = {
    "move_to_shared": move_to_shared,
    "list_data_files": list_data_files,
    "add_task_comment": add_task_comment,
    "send_message_now": send_message_now,
}


async def _handle_tool(request: Request) -> JSONResponse:
    name = request.path_params.get("name", "")
    fn = _TOOL_REGISTRY.get(name)
    if fn is None:
        return JSONResponse(
            {"error": f"Unknown tool '{name}'. Allowed: {sorted(_TOOL_REGISTRY)}"},
            status_code=404,
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Request body must be a JSON object of keyword arguments."},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Request body must be a JSON object (kwargs), got "
                      f"{type(payload).__name__}."},
            status_code=400,
        )

    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(**payload)
        else:
            result = fn(**payload)
    except TypeError as e:
        # Almost always a bad/missing kwarg from the caller.
        logger.warning(f"[http_api] {name} bad args: {e}")
        return JSONResponse({"error": f"Bad arguments for {name}: {e}"}, status_code=400)
    except Exception as e:
        logger.exception(f"[http_api] {name} raised")
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    return JSONResponse({"result": result if result is not None else ""})


async def _handle_progress(request: Request) -> JSONResponse:
    """Live progress panel sink. ALWAYS 200 — a panel failure must never
    propagate to the agent/executor. Body:
      {action:"step", key, recipient, channel, session_id, agent,
       tool, phase:"start"|"end", ok:bool}
      {action:"finalize", key, status:"done"|"failed"}
    """
    try:
        from core.notifiers.progress_panel import panel_step, panel_finalize
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"ok": False}, status_code=200)
        action = body.get("action", "step")
        if action == "finalize":
            await panel_finalize(body.get("key"), body.get("status", "done"))
        else:
            await panel_step(
                key=body.get("key"),
                recipient=body.get("recipient"),
                channel=body.get("channel"),
                session_id=body.get("session_id"),
                agent=body.get("agent"),
                tool=body.get("tool"),
                phase=body.get("phase", "start"),
                ok=bool(body.get("ok", True)),
            )
    except Exception:
        logger.exception("[http_api] progress_step swallowed")
    return JSONResponse({"ok": True}, status_code=200)


def register_http_api(app) -> None:
    """Attach the /api/tool/{name} + /api/progress_step routes to an
    existing Starlette app.

    Called from server.py with the app returned by
    ``mcp.streamable_http_app()`` BEFORE the Bearer middleware wraps it,
    so the same MCP_SECRET_KEY protects these endpoints too.
    """
    app.router.routes.append(
        Route("/api/tool/{name}", _handle_tool, methods=["POST"])
    )
    app.router.routes.append(
        Route("/api/progress_step", _handle_progress, methods=["POST"])
    )
    logger.info(
        "HTTP tool shim mounted: POST /api/tool/{name} "
        f"({', '.join(sorted(_TOOL_REGISTRY))}); POST /api/progress_step"
    )
