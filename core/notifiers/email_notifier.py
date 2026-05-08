import logging
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def send_email_notification(recipient_email: str, message: str, subject: str = None):
    """Sends a notification email via SMTP.

    Args:
        recipient_email (str): The recipient's email address.
        message (str): The body content of the email.
        subject (str): The subject of the email.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    
    if not all([smtp_server, smtp_user, smtp_pass]):
        logger.error("Email credentials not fully configured (SMTP_SERVER, SMTP_USER, SMTP_PASSWORD)")
        return False

    # Use default subject if not provided
    email_subject = subject if subject else "ADK Scheduled Reminder"

    msg = MIMEText(message)
    msg['Subject'] = email_subject
    msg['From'] = smtp_user
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Email send failed")
        return False
