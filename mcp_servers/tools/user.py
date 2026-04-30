import json
from typing import Optional

from core import models
from core.database import SessionLocal
from core.license import LicenseManager
from mcp_servers.setup import mcp, tz
from mcp_servers.background import _ensure_default_regular_works
from datetime import datetime


@mcp.tool()
async def get_user_profile(user_id: str) -> str:
    """Retrieves the user's personal profile (name, job, company, email, etc.)."""
    db = SessionLocal()
    try:
        profile = db.query(models.UserContact).filter(models.UserContact.user_id == user_id).first()
        if not profile:
            return f"No profile found for user {user_id}."
        # Lazily create default Regular Works for users who don't have them yet
        _ensure_default_regular_works(user_id)
        data = {
            "Chinese Name": profile.chinese_name,
            "English Name": profile.english_name,
            "Job Title": profile.job_title,
            "Company": profile.company_name,
            "Email": profile.personal_email,
            "Phone": profile.mobile_phone,
            "Employee ID": profile.employee_id,
            "Note": profile.note
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def update_user_profile(
    user_id: str,
    chinese_name: Optional[str] = None,
    english_name: Optional[str] = None,
    job_title: Optional[str] = None,
    company_name: Optional[str] = None,
    personal_email: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    employee_id: Optional[str] = None,
    note: Optional[str] = None
) -> str:
    """Updates or creates the user's personal profile."""
    db = SessionLocal()
    try:
        profile = db.query(models.UserContact).filter(models.UserContact.user_id == user_id).first()
        if not profile:
            LicenseManager.check_user_limit(db)
            profile = models.UserContact(user_id=user_id)
            db.add(profile)
        if chinese_name is not None: profile.chinese_name = chinese_name
        if english_name is not None: profile.english_name = english_name
        if job_title is not None: profile.job_title = job_title
        if company_name is not None: profile.company_name = company_name
        if personal_email is not None: profile.personal_email = personal_email
        if mobile_phone is not None: profile.mobile_phone = mobile_phone
        if employee_id is not None: profile.employee_id = employee_id
        if note is not None: profile.note = note
        db.commit()
        return f"Profile updated for {user_id}."
    except Exception as e:
        db.rollback()
        return f"Error: {str(e)}"
    finally:
        db.close()


@mcp.tool()
async def get_current_time() -> str:
    """Returns the current date and time in the configured timezone."""
    return datetime.now(tz).isoformat()


@mcp.tool()
async def check_identity(user_id: str) -> str:
    """Checks whether a user ID is known in the system."""
    db = SessionLocal()
    user = db.query(models.UserContact).filter(models.UserContact.user_id == user_id).first()
    if user and user.chinese_name:
        name = user.chinese_name
        db.close()
        return f"FOUND: {name}"
    mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == user_id).first()
    db.close()
    return "KNOWN_ID" if mapping else "NOT_FOUND"
