import os
import logging
import pytz
from mcp.server.fastmcp import FastMCP
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.database import SessionLocal, engine, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("costaff-agent-engine")

tz = pytz.timezone(os.getenv("TIMEZONE", "UTC"))

mcp = FastMCP("CoStaff", host="0.0.0.0", port=int(os.getenv("MCP_COSTAFF_PORT", "8081")), stateless_http=True)
scheduler = AsyncIOScheduler(timezone=tz)

# Track jobs already added to scheduler
scheduled_job_ids = set()
