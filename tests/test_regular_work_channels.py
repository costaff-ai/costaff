"""Multi-channel delivery targets on RegularWork (migration 0002 + router helpers)."""
import json
import os

from sqlalchemy import create_engine, inspect, text

from server.routers.regular_works import _normalize_targets, _parse_targets_row, _target_columns
from server.schemas import ChannelTarget, RegularWorkCreateRequest, RegularWorkUpdateRequest
from utils.paths import _project_root


# --- migration -------------------------------------------------------------

def _cfg(url, monkeypatch):
    from alembic.config import Config

    monkeypatch.setenv("COSTAFF_ALEMBIC_URL", url)
    cfg = Config(os.path.join(_project_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_project_root, "migrations"))
    return cfg


def test_migration_adds_channels_to_legacy_db(tmp_path, monkeypatch):
    """A DB stamped at 0001 before `channels` existed gets the column via 0002."""
    from alembic import command

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text(
            "CREATE TABLE regular_works (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR, "
            "session_id VARCHAR, title VARCHAR, spec VARCHAR, cron VARCHAR, agent_id VARCHAR, "
            "channel VARCHAR, recipient VARCHAR, status VARCHAR, silent BOOLEAN, "
            "last_run DATETIME, next_run DATETIME, created_at DATETIME, updated_at DATETIME)"
        ))

    cfg = _cfg(url, monkeypatch)
    command.stamp(cfg, "0001_baseline")
    command.upgrade(cfg, "head")

    cols = {c["name"] for c in inspect(eng).get_columns("regular_works")}
    assert "channels" in cols


def test_migration_idempotent_on_fresh_db(tmp_path, monkeypatch):
    """Fresh DB: baseline already materialises `channels`; 0002 must not raise."""
    from alembic import command

    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    command.upgrade(_cfg(url, monkeypatch), "head")  # must not raise

    cols = {c["name"] for c in inspect(create_engine(url)).get_columns("regular_works")}
    assert "channels" in cols


# --- router helpers ----------------------------------------------------------

def test_normalize_prefers_channels_list():
    req = RegularWorkCreateRequest(
        title="t", spec="s", cron="0 9 * * *",
        channel="telegram", recipient="legacy-ignored",
        channels=[ChannelTarget(channel="line", recipient="U1"),
                  ChannelTarget(channel="discord", recipient="D2")],
    )
    assert _normalize_targets(req) == [
        {"channel": "line", "recipient": "U1"},
        {"channel": "discord", "recipient": "D2"},
    ]


def test_normalize_falls_back_to_legacy_pair():
    req = RegularWorkUpdateRequest(channel="telegram", recipient="123")
    assert _normalize_targets(req) == [{"channel": "telegram", "recipient": "123"}]


def test_normalize_skips_blank_channels():
    req = RegularWorkUpdateRequest(channels=[
        ChannelTarget(channel="  ", recipient="x"),
        ChannelTarget(channel="slack", recipient="  C9  "),
    ])
    assert _normalize_targets(req) == [{"channel": "slack", "recipient": "C9"}]


def test_target_columns_mirror_first_pair():
    cols = _target_columns([
        {"channel": "telegram", "recipient": "111"},
        {"channel": "line", "recipient": "222"},
    ])
    assert cols["channel"] == "telegram"
    assert cols["recipient"] == "111"
    assert json.loads(cols["channels"]) == [
        {"channel": "telegram", "recipient": "111"},
        {"channel": "line", "recipient": "222"},
    ]


def test_target_columns_empty_clears_everything():
    assert _target_columns([]) == {"channels": None, "channel": None, "recipient": None}


def test_parse_row_decodes_json():
    row = {"channel": "telegram", "recipient": "1",
           "channels": json.dumps([{"channel": "line", "recipient": "U9"}])}
    assert _parse_targets_row(row)["channels"] == [{"channel": "line", "recipient": "U9"}]


def test_parse_row_falls_back_to_legacy_on_missing_or_bad_json():
    legacy = _parse_targets_row({"channel": "telegram", "recipient": "1", "channels": None})
    assert legacy["channels"] == [{"channel": "telegram", "recipient": "1"}]

    garbage = _parse_targets_row({"channel": "discord", "recipient": "2", "channels": "{not-json"})
    assert garbage["channels"] == [{"channel": "discord", "recipient": "2"}]

    none = _parse_targets_row({"channel": None, "recipient": None, "channels": None})
    assert none["channels"] == []
