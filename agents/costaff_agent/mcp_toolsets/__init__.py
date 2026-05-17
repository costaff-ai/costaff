"""MCP toolset loader: read configuration from environment and build a list of McpToolset.

Usage:
    from mcp_toolsets import load_all_mcp_toolsets
    toolsets = load_all_mcp_toolsets()  # returns a list of McpToolset

Environment variable lookup order: COSTAFF_AGENT_MCP_URLS → MCP_SERVER_URLS.
Supported formats:
    1. JSON object: {"name": {"url": "...", "headers": {...}, "transport": "sse|streamable", "enabled": true}}
    2. JSON string-mapped: {"name": "url", ...}
    3. Comma-separated URL string: "url1,url2,url3"

Note: this folder is named mcp_toolsets/ (not mcp/) to avoid collision with
the google-adk MCP SDK package (mcp), which lives in site-packages.
"""
import json
import logging
import os
import re
from typing import List

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    SseServerParams,
    StreamableHTTPServerParams,
)

logger = logging.getLogger(__name__)


def _get_connection_params(entry):
    """Return ADK ServerParams based on the entry's url / headers / transport.

    Transport precedence:
      1. explicit `transport` field on the entry, else
      2. global MCP_TRANSPORT env (default "streamable-http"), else
      3. inferred from the URL's /sse|/mcp suffix.
    SSE is race-free under to_a2a()+ADK1.33 (the streamable-http anyio
    CancelScope race #4454 does NOT occur on SSE — verified 2026-05-16).
    The URL suffix is normalised to match the chosen transport so
    dashboard-generated `.../mcp` URLs work under SSE too.
    """
    if isinstance(entry, str):
        url, headers, transport = entry, None, None
    else:
        url = entry.get("url", "")
        headers = entry.get("headers") or None
        transport = entry.get("transport")

    if not url:
        raise ValueError("MCP entry has no URL")
    if transport is None:
        transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
    # normalise both alias spellings
    if transport in ("streamable", "streamable-http", "streamable_http"):
        transport = "streamable"

    base = re.sub(r"/(mcp|sse)/?$", "", url.rstrip("/"))
    if transport == "sse":
        return SseServerParams(url=base + "/sse", headers=headers)
    return StreamableHTTPServerParams(url=base + "/mcp", headers=headers)


def load_all_mcp_toolsets() -> List[McpToolset]:
    """Read MCP configuration from environment and build a list of McpToolset.

    Returns:
        List[McpToolset]: registered MCP toolsets, ready to drop into Agent(tools=[...]).

    Raises:
        EnvironmentError: when neither COSTAFF_AGENT_MCP_URLS nor MCP_SERVER_URLS is set.
    """
    raw = os.getenv("COSTAFF_AGENT_MCP_URLS") or os.getenv("MCP_SERVER_URLS", "")
    if not raw:
        raise EnvironmentError(
            "COSTAFF_AGENT_MCP_URLS (or MCP_SERVER_URLS) is not set."
        )

    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        config = {
            f"mcp_{i}": url.strip()
            for i, url in enumerate(raw.split(","))
            if url.strip()
        }

    toolsets: List[McpToolset] = []
    for name, entry in config.items():
        if isinstance(entry, dict) and not entry.get("enabled", True):
            continue
        try:
            toolsets.append(
                McpToolset(connection_params=_get_connection_params(entry))
            )
            logger.info(f"Registered MCP: {name}")
        except Exception:
            logger.exception("FAILED to load MCP '%s'", name)
    return toolsets
