import json
from datetime import datetime

from sqlalchemy import text as sa_text

from core.database import SessionLocal
from mcp_servers.setup import mcp, tz


@mcp.tool()
async def read_today_events(user_id: str) -> str:
    """
    Reads today's conversation events for the given user from the ADK events table.
    Used by the nightly diary writing RegularWork to summarize the day.
    Returns a readable transcript of today's agent activity.
    """
    db = SessionLocal()
    try:
        # `events.event_data` is ADK-owned JSON that does NOT contain user_id —
        # the link to the user is via `sessions.user_id`. Join through there
        # rather than substring-matching the JSON text.
        today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.strftime("%Y-%m-%d")

        result = db.execute(
            sa_text(
                "SELECT e.event_data, e.\"timestamp\" "
                "FROM events e "
                "JOIN sessions s ON e.session_id = s.id "
                "WHERE s.user_id = :user_id "
                "  AND e.\"timestamp\" >= :today_start "
                "ORDER BY e.\"timestamp\" ASC LIMIT 200"
            ),
            {"user_id": user_id, "today_start": today_start},
        ).fetchall()

        if not result:
            return f"No events found for today ({today_str})."

        transcript = []
        for row in result:
            ed = row[0]
            if isinstance(ed, str):
                ed = json.loads(ed)
            author = ed.get("author", "unknown")
            parts = ed.get("content", {}).get("parts", [])
            for part in parts:
                text = part.get("text", "").strip()
                if text:
                    transcript.append(f"[{author}] {text}")

        if not transcript:
            return f"No readable events found for today ({today_str})."

        return "\n".join(transcript[:100])  # Cap at 100 lines
    except Exception as e:
        return f"Error reading events: {str(e)}"
    finally:
        db.close()
