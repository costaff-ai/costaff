"""`costaff database backup/clean/restore` must fail friendly when no DB
is configured, not dump an AttributeError traceback.

Regression for the audit: get_engine() returns None when
ADK_SESSION_SERVICE_URI is unset, and these three commands called
.connect() on it. db migrate/history already handled this; now they match.
"""
import pytest
import typer

import cli.commands.database as db


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(db.DatabaseManager, "get_engine", staticmethod(lambda: None))


def test_backup_no_db_exits_cleanly(no_db):
    with pytest.raises(typer.Exit) as exc:
        db.backup(output=None)
    assert exc.value.exit_code == 1


def test_clean_no_db_exits_cleanly(no_db, monkeypatch):
    # Confirm "yes" so we reach the engine acquisition
    monkeypatch.setattr(db.questionary, "confirm",
                        lambda *a, **k: type("C", (), {"ask": lambda self: True})())
    with pytest.raises(typer.Exit) as exc:
        db.clean()
    assert exc.value.exit_code == 1


def test_restore_no_db_exits_cleanly(no_db, tmp_path):
    backup_file = tmp_path / "b.json"
    backup_file.write_text('{"tables": {}}')
    with pytest.raises(typer.Exit) as exc:
        db.restore(str(backup_file))
    assert exc.value.exit_code == 1


def test_restore_missing_file_exits_nonzero(monkeypatch):
    # Missing file must exit non-zero (was: print + implicit exit 0)
    with pytest.raises(typer.Exit) as exc:
        db.restore("/nope/does-not-exist.json")
    assert exc.value.exit_code == 1


def test_require_engine_returns_engine_when_present(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(db.DatabaseManager, "get_engine", staticmethod(lambda: sentinel))
    assert db._require_engine() is sentinel
