import json
from datetime import datetime, timedelta

from sqlalchemy import text as sa_text

from core.database import SessionLocal
from mcp_servers.setup import mcp, tz


@mcp.tool()
async def read_today_events(user_id: str, date_str: str = "") -> str:
    """
    Reads conversation events for the given user from the ADK events table.

    - user_id: the user whose events to read (linked via sessions.user_id).
    - date_str: optional YYYY-MM-DD. Empty/omitted = today. Pass a past
      date to backfill an old daily diary.

    Used by the nightly diary writing RegularWork to summarize the day,
    and by manual backfill flows for past days.
    """
    db = SessionLocal()
    try:
        # `events.event_data` is ADK-owned JSON that does NOT contain user_id —
        # the link to the user is via `sessions.user_id`. Join through there
        # rather than substring-matching the JSON text.
        if date_str:
            try:
                day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
            except ValueError:
                return f"Invalid date_str '{date_str}'. Expected YYYY-MM-DD."
        else:
            day_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        day_label = day_start.strftime("%Y-%m-%d")

        result = db.execute(
            sa_text(
                "SELECT e.event_data, e.\"timestamp\" "
                "FROM events e "
                "JOIN sessions s ON e.session_id = s.id "
                "WHERE s.user_id = :user_id "
                "  AND e.\"timestamp\" >= :day_start "
                "  AND e.\"timestamp\" <  :day_end "
                "ORDER BY e.\"timestamp\" ASC LIMIT 200"
            ),
            {"user_id": user_id, "day_start": day_start, "day_end": day_end},
        ).fetchall()

        if not result:
            return f"No events found for {day_label}."

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
            return f"No readable events found for {day_label}."

        return "\n".join(transcript[:100])  # Cap at 100 lines
    except Exception as e:
        return f"Error reading events: {str(e)}"
    finally:
        db.close()
