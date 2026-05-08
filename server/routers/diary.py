import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text

from services.auth import AuthManager
from services.database import DatabaseManager
from utils.serialization import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/diary")
def list_diary(days: int = 7, auth: bool = Depends(AuthManager.verify_token)):
    engine = DatabaseManager.get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(
                "SELECT id, user_id, agent_name, date, type, done, blocker, next, created_at "
                "FROM diary ORDER BY date DESC, agent_name ASC LIMIT :lim"
            ), {"lim": days * 10})
            return [_serialize_row(dict(r._mapping)) for r in res]
    except Exception:
        logger.exception("list_diary failed")
        return []
