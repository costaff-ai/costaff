import os
import sys
import asyncio

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from mcp_servers.setup import mcp, scheduler, scheduled_job_ids, logger, tz
from core.database import SessionLocal, init_db
from core import models
from core.license import LicenseManager

# Import all tool modules to register @mcp.tool() decorators
from mcp_servers.tools import user, messaging, reminders, regular_works, epics, stories, project_tasks, task_comments, diary, events, apis, skills, workspace

# Import background task functions
from mcp_servers.background import (
    sync_database_tasks, poll_queued_tasks, _ensure_default_regular_works,
    recover_orphaned_tasks, orphan_sweep_loop,
)
from mcp_servers.executors.reminder import execute_reminder


async def startup():
    try:
        LicenseManager.load()
    except ValueError as e:
        # Decisions A+B+C: a degraded license (expired / tampered / wrong
        # machine) must NOT crash the core. Keep serving on OSS limits;
        # the runtime usage gate (require_within_license) blocks real work
        # only if usage exceeds OSS limits, and a freshly applied license
        # is picked up without a restart.
        logger.error(f"LICENSE DEGRADED → OSS limits, continuing to serve: {e}")

    init_db()
    if not scheduler.running:
        scheduler.start()

    # Recover orphaned ProjectTasks — anything stuck in 'doing' from before
    # this MCP container started up. All executors died with the previous
    # process, so max_age_minutes=0 reaps every 'doing' row unconditionally
    # (the old 30-minute gate left restart-within-30min tasks stuck forever).
    # Must run before the queue polling kicks in so a stale 'doing' record
    # isn't counted as 'busy'.
    await recover_orphaned_tasks(max_age_minutes=0)

    # Ensure default global Regular Works exist (shared across all users)
    _ensure_default_regular_works()

    # Pre-load pending reminders
    db = SessionLocal()
    try:
        from apscheduler.triggers.date import DateTrigger
        pending = db.query(models.Reminder).filter(models.Reminder.status == "pending").all()
        for r in pending:
            if r.run_at:
                job_id = f"reminder_{r.id}"
                try:
                    run_time = r.run_at.replace(tzinfo=tz) if r.run_at.tzinfo is None else r.run_at
                    scheduler.add_job(
                        execute_reminder, DateTrigger(run_date=run_time),
                        args=[r.id], id=job_id, replace_existing=True
                    )
                    scheduled_job_ids.add(job_id)
                except Exception:
                    logger.exception("Failed to pre-load reminder %s", r.id)
    finally:
        db.close()

    asyncio.create_task(sync_database_tasks())
    asyncio.create_task(poll_queued_tasks())
    asyncio.create_task(orphan_sweep_loop())
    logger.info("CoStaff Agent Engine online.")


if __name__ == "__main__":
    async def main():
        await startup()
        import uvicorn
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response as StarletteResponse

        # Transport env-selectable. Default SSE: race-free under
        # to_a2a()+ADK1.33 (streamable-http anyio CancelScope race #4454
        # does NOT occur on SSE — verified 2026-05-16). The /api/tool
        # shim is mounted on whichever app, so it keeps working either
        # way. MCP_TRANSPORT=streamable-http to switch back once ADK
        # fixes #4454.
        _transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
        if _transport == "streamable-http":
            starlette_app = mcp.streamable_http_app()
            logger.info("MCP transport: streamable-http (endpoint: /mcp)")
        else:
            starlette_app = mcp.sse_app()
            logger.info("MCP transport: sse (endpoint: /sse)")

        # Mount the plain-HTTP shim for the shared cross-agent tools so
        # plugins can call them with httpx instead of a 2nd MCP session
        # (which triggers the anyio CancelScope race). Added BEFORE the
        # Bearer wrap below so the same MCP_SECRET_KEY guards it.
        from mcp_servers.http_api import register_http_api
        register_http_api(starlette_app)

        mcp_secret = os.getenv("MCP_SECRET_KEY")
        if mcp_secret:
            class BearerMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    auth = request.headers.get("authorization", "")
                    if auth != f"Bearer {mcp_secret}":
                        return StarletteResponse("Unauthorized", status_code=401)
                    return await call_next(request)
            starlette_app = BearerMiddleware(starlette_app)
            logger.info("MCP Bearer token authentication enabled.")
        else:
            logger.warning("MCP_SECRET_KEY not set — running without authentication.")

        config = uvicorn.Config(
            starlette_app,
            host="0.0.0.0",
            port=int(os.getenv("MCP_COSTAFF_PORT", "8081")),
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(main())
