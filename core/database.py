import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv("ADK_SESSION_SERVICE_URI") or os.getenv("SQLALCHEMY_DATABASE_URL")
if not uri:
    raise RuntimeError(
        "Database URI not configured. "
        "Set ADK_SESSION_SERVICE_URI=postgresql+asyncpg://user:pass@host:5432/db in .env"
    )

# Strip async driver prefix — SQLAlchemy ORM needs the sync driver
if "+asyncpg" in uri:
    uri = uri.replace("+asyncpg", "")
if "+aiosqlite" in uri:
    raise RuntimeError(
        "SQLite is not supported. Use PostgreSQL: "
        "ADK_SESSION_SERVICE_URI=postgresql+asyncpg://user:pass@host:5432/db"
    )

SQLALCHEMY_DATABASE_URL = uri

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    with engine.connect() as conn:
        # Drop legacy tables replaced by the new schema
        for legacy in ("tasks", "task_logs"):
            if legacy in existing:
                conn.execute(text(f"DROP TABLE IF EXISTS {legacy} CASCADE"))
                conn.commit()

        # Migrate reminders: drop and recreate if it uses the old schema
        if "reminders" in existing:
            old_cols = {c["name"] for c in inspector.get_columns("reminders")}
            if "prompt" in old_cols or "cron" in old_cols:
                conn.execute(text("DROP TABLE IF EXISTS reminders CASCADE"))
                conn.commit()

        # identity_maps migrations
        if "identity_maps" in existing:
            cols = {c["name"] for c in inspector.get_columns("identity_maps")}
            if "session_id" not in cols:
                from .models import IdentityMap
                IdentityMap.__table__.drop(engine)
            else:
                if "is_approved" not in cols:
                    conn.execute(text(
                        "ALTER TABLE identity_maps ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                    conn.commit()
                if "updated_at" not in cols:
                    conn.execute(text(
                        "ALTER TABLE identity_maps ADD COLUMN updated_at TIMESTAMP"
                    ))
                    conn.commit()

        # api_configs / skill_configs: add agent_ids if missing
        for tbl in ("api_configs", "skill_configs"):
            if tbl in existing:
                cols = {c["name"] for c in inspector.get_columns(tbl)}
                if "agent_ids" not in cols:
                    conn.execute(text(
                        f"ALTER TABLE {tbl} ADD COLUMN agent_ids VARCHAR DEFAULT '__all__'"
                    ))
                    conn.commit()

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
