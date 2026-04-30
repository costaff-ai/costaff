"""Tests for mcp_servers.tools._shared.require_approved.

The gate denies access only to users who have an `IdentityMap` row that is
explicitly not approved. Users with no mapping (admin / system) pass through.
"""
from datetime import datetime

from core import models
from mcp_servers.tools._shared import require_approved


def _add_identity(db, hashed_id: str, *, is_approved: bool):
    db.add(models.IdentityMap(
        session_id=f"sess-{hashed_id}",
        hashed_id=hashed_id,
        real_id=f"real-{hashed_id}",
        is_approved=is_approved,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))
    db.commit()


def test_no_identity_map_returns_none(db_session):
    """Admin / system users have no row — gate is permissive."""
    assert require_approved("unmapped-user", db_session) is None


def test_approved_identity_returns_none(db_session):
    _add_identity(db_session, "user-ok", is_approved=True)
    assert require_approved("user-ok", db_session) is None


def test_unapproved_identity_returns_denial_message(db_session):
    _add_identity(db_session, "user-pending", is_approved=False)
    msg = require_approved("user-pending", db_session)
    assert msg is not None
    assert "not been approved" in msg


def test_only_matches_on_hashed_id(db_session):
    """The lookup is by hashed_id, not real_id."""
    _add_identity(db_session, "hashed-abc", is_approved=False)
    # Querying with the real_id should not match — gate stays permissive.
    assert require_approved("real-hashed-abc", db_session) is None
