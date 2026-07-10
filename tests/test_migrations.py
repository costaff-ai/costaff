"""Tests for the alembic migration wiring (feature #3).

Exercises the real env.py + baseline migration end-to-end against a
file-backed SQLite DB — no Postgres or Docker required.
"""
import os

from sqlalchemy import create_engine, inspect

from utils.paths import _project_root


def _cfg(url, monkeypatch):
    from alembic.config import Config

    monkeypatch.setenv("COSTAFF_ALEMBIC_URL", url)
    cfg = Config(os.path.join(_project_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_project_root, "migrations"))
    return cfg


def test_single_head(monkeypatch):
    """The migration graph must stay linear — exactly one head."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg("sqlite://", monkeypatch))
    assert list(script.get_heads()) == ["0003_notification_outbox"]


def test_upgrade_head_creates_core_schema(tmp_path, monkeypatch):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'core.db'}"
    command.upgrade(_cfg(url, monkeypatch), "head")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"identity_maps", "reminders", "project_tasks",
            "notification_outbox", "costaff_alembic_version"} <= tables


def test_core_uses_dedicated_version_table(tmp_path, monkeypatch):
    """A foreign alembic_version (e.g. webchat-enterprise sharing the DB) must
    not block the core: we track our own `costaff_alembic_version` and leave
    the other environment's table untouched. Reproduces the asst-core crash."""
    from alembic import command
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'shared.db'}"
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        c.execute(text("INSERT INTO alembic_version VALUES ('0002_totp_2fa')"))

    command.upgrade(_cfg(url, monkeypatch), "head")  # must not raise

    tables = set(inspect(eng).get_table_names())
    assert "costaff_alembic_version" in tables
    assert "identity_maps" in tables
    with eng.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002_totp_2fa"


def test_downgrade_to_base_drops_core_schema(tmp_path, monkeypatch):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'core.db'}"
    cfg = _cfg(url, monkeypatch)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert "identity_maps" not in tables


def test_bootstrap_sqlite_skips_alembic(tmp_path, monkeypatch):
    """The SQLite path must create tables via create_all, not alembic."""
    import core.database as cdb

    eng = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    monkeypatch.setattr(cdb, "engine", eng)

    cdb._bootstrap_schema()

    tables = set(inspect(eng).get_table_names())
    assert "identity_maps" in tables
    assert "alembic_version" not in tables
    assert "costaff_alembic_version" not in tables
