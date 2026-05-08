import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from utils.paths import PATHS


class DatabaseManager:
    @staticmethod
    def get_engine():
        load_dotenv(PATHS["env"])
        uri = os.getenv("ADK_SESSION_SERVICE_URI", "")
        if not uri:
            return None
        # Strip async driver for sync SQLAlchemy usage in dashboard
        uri = uri.replace("postgresql+asyncpg://", "postgresql://")
        # Allow dashboard running on host to reach postgres container
        if "postgres:5432" in uri:
            uri = uri.replace("postgres:5432", "localhost:5432")
        try:
            return create_engine(uri, pool_pre_ping=True)
        except Exception:
            return None

    @staticmethod
    def get_table_counts():
        engine = DatabaseManager.get_engine()
        if not engine:
            return {}
        counts = {}
        tables = ["events", "sessions", "user_states", "reminders", "regular_works", "epics", "project_tasks", "diary", "identity_maps", "file_tasks", "user_contacts", "contacts"]
        with engine.connect() as conn:
            for t in tables:
                try:
                    counts[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                except Exception:
                    counts[t] = "N/A"
        return counts
