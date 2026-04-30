import json
from datetime import datetime

from sqlalchemy import text as sa_text

from core.database import SessionLocal
from mcp_servers.core import mcp, tz


@mcp.tool()
async def read_today_events(user_id: str) -> str:
    """
    Reads today's conversation events from the ADK events table.
    Used by the nightly diary writing RegularWork to summarize the day.
    Returns a readable transcript of today's agent activity.
    """
    db = SessionLocal()
    try:
        today = datetime.now(tz).strftime("%Y-%m-%d")
        result = db.execute(
            sa_text(
                "SELECT event_data, \"timestamp\" FROM events "
                "WHERE event_data::text LIKE :uid_pattern "
                "ORDER BY \"timestamp\" ASC LIMIT 200"
            ),
            {"uid_pattern": f"%{user_id}%"}
        ).fetchall()

        if not result:
            return f"No events found for today ({today})."

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
            return "No readable events found for today."

        return "\n".join(transcript[:100])  # Cap at 100 lines
    except Exception as e:
        return f"Error reading events: {str(e)}"
    finally:
        db.close()
