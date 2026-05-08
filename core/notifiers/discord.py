import httpx
import logging
import os
from dotenv import load_dotenv
from core import models
from core.database import SessionLocal

load_dotenv()
logger = logging.getLogger(__name__)

def send_discord_notification(recipient_id: str, message: str, session_id: str = None):
    """
    Sends a notification to a Discord Channel or User.
    Prioritizes session_id for precise routing in multi-server environments.
    """
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not found")
        return False
    
    final_destination = recipient_id # Default fallback
    db = SessionLocal()
    
    try:
        # 1. Primary: Use Session ID to find the EXACT channel this reminder was created in
        if session_id:
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.session_id == session_id).first()
            if mapping:
                final_destination = mapping.real_id
        # 2. Fallback: Use hashed_id to find the last known channel for this user
        elif len(recipient_id) == 16 and not recipient_id.isdigit():
            mapping = db.query(models.IdentityMap).filter(models.IdentityMap.hashed_id == recipient_id).first()
            if mapping:
                final_destination = mapping.real_id
    finally:
        db.close()

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    
    with httpx.Client(timeout=10.0) as client:
        try:
            # Try sending to the resolved channel/destination
            url_msg = f"https://discord.com/api/v10/channels/{final_destination}/messages"
            res_msg = client.post(url_msg, headers=headers, json={"content": message})
            
            if res_msg.status_code == 200:
                return True
            
            # DM Fallback if channel send fails
            url_dm = "https://discord.com/api/v10/users/@me/channels"
            res_dm = client.post(url_dm, headers=headers, json={"recipient_id": final_destination})
            if res_dm.status_code == 200:
                dm_channel_id = res_dm.json().get("id")
                url_msg_dm = f"https://discord.com/api/v10/channels/{dm_channel_id}/messages"
                res_final = client.post(url_msg_dm, headers=headers, json={"content": message})
                return res_final.status_code == 200
            
            return False
        except Exception:
            logger.exception("Discord notification failed")
            return False
