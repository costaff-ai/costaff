"""Shared helpers used across multiple MCP tool modules."""
from core import models


def require_approved(user_id: str, db) -> "str | None":
    """Return a denial message if the user is unapproved, else None.

    Users with no identity_maps record (admin / system) are always
    granted access — the gate only applies to users who have signed
    in but have not been approved by an operator.
    """
    mapping = db.query(models.IdentityMap).filter(
        models.IdentityMap.hashed_id == user_id
    ).first()
    if mapping is not None and not mapping.is_approved:
        return "Access denied: your account has not been approved. Please contact an administrator."
    return None
