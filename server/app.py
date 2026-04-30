import os
import json
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from utils.helpers import PATHS
from server.routers import auth, system, config, agents, diary, identity, chat_inspect, integrations, proxies, regular_works, project


def _setup_logging() -> None:
    class _JSONFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            data = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                data["exc"] = self.formatException(record.exc_info)
            return json.dumps(data, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )

_setup_logging()

server = FastAPI(title="CoStaff Dashboard")
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
server.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
server.mount("/css", StaticFiles(directory=os.path.join(PATHS["frontend"], "css")), name="css")
server.mount("/js", StaticFiles(directory=os.path.join(PATHS["frontend"], "js")), name="js")
server.mount("/views", StaticFiles(directory=os.path.join(PATHS["frontend"], "views")), name="views")

# Include all routers
server.include_router(auth.router)
server.include_router(system.router)
server.include_router(config.router)
server.include_router(agents.router)
server.include_router(project.router)
server.include_router(diary.router)
server.include_router(identity.router)
server.include_router(chat_inspect.router)
server.include_router(integrations.router)
server.include_router(proxies.router)
server.include_router(regular_works.router)


@server.get("/")
def read_index():
    return FileResponse(os.path.join(PATHS["frontend"], "index.html"))
