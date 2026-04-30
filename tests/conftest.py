"""Shared pytest fixtures for the costaff test suite.

`core/database.py` raises at import time when no DB URI is configured, so we
set a SQLite URI before any test module imports `core`.
"""
import os
import sys
from pathlib import Path

# Make the repo root importable regardless of where pytest is invoked from.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Must be set before `core.database` is imported anywhere.
os.environ.setdefault("ADK_SESSION_SERVICE_URI", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base


@pytest.fixture
def db_session():
    """Yields a SQLAlchemy session bound to a fresh in-memory SQLite DB.

    Each test gets an isolated database — schema is created from the ORM
    metadata, and the engine is disposed after the test.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
