"""
CoStaff License Manager
Validates Ed25519-signed YAML license files and enforces plan limits.
"""
import os
import platform
import subprocess
import hashlib
import base64
import logging
import yaml
from datetime import date, datetime
from typing import Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# --- Public key (hardcoded — private key is kept by the licensor) ---
_PUBLIC_KEY_B64 = "L2TjTtry0aSRj9nEBXWZ7CwYRZHPn0teBVE5PgdWT2Y="

# --- OSS Plan limits ---
OSS_LIMITS = {
    "max_agents": 1,
    "max_users":  1,
    "max_skills": 10,
}


def get_machine_id() -> str:
    """
    Returns a stable, hashed machine identifier.
    macOS : IOPlatformUUID via ioreg
    Linux : /etc/machine-id
    The raw value is SHA-256 hashed so the actual system ID is never exposed.
    """
    try:
        system = platform.system()
        if system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL
            ).decode()
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    raw = line.split('"')[-2]
                    return hashlib.sha256(raw.encode()).hexdigest()[:32]
        elif system == "Linux":
            with open("/etc/machine-id", "r") as f:
                raw = f.read().strip()
            return hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception as e:
        logger.warning(f"Could not detect machine ID: {e}")
    return "unknown"


def _load_public_key() -> Ed25519PublicKey:
    raw = base64.b64decode(_PUBLIC_KEY_B64)
    return Ed25519PublicKey.from_public_bytes(raw)


def _canonical(data: dict) -> bytes:
    """
    Produces a deterministic byte string from the license data (excluding signature)
    that is used as the signed payload.
    """
    fields = [
        f"license_id={data.get('license_id', '')}",
        f"plan={data.get('plan', '')}",
        f"issued_to={data.get('issued_to', '')}",
        f"contact_phone={data.get('contact_phone', '')}",
        f"issued_at={data.get('issued_at', '')}",
        f"expires_at={data.get('expires_at', '')}",
        f"machine_id={data.get('machine_id', '')}",
        f"max_agents={data.get('limits', {}).get('max_agents', 0)}",
        f"max_users={data.get('limits', {}).get('max_users', 0)}",
        f"max_skills={data.get('limits', {}).get('max_skills', 0)}",
    ]
    return "\n".join(fields).encode("utf-8")


class LicenseInfo:
    def __init__(self, plan: str, issued_to: str, expires_at: Optional[date], limits: dict,
                 contact_phone: str = ""):
        self.plan = plan
        self.issued_to = issued_to
        self.contact_phone = contact_phone
        self.expires_at = expires_at
        self.limits = limits

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return date.today() > self.expires_at

    @property
    def max_agents(self) -> int:
        return self.limits.get("max_agents", OSS_LIMITS["max_agents"])

    @property
    def max_users(self) -> int:
        return self.limits.get("max_users", OSS_LIMITS["max_users"])

    @property
    def max_skills(self) -> int:
        return self.limits.get("max_skills", OSS_LIMITS["max_skills"])


class LicenseManager:
    _license: Optional[LicenseInfo] = None

    DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".costaff", "costaff-license.yaml")

    @classmethod
    def load(cls, path: Optional[str] = None) -> Optional[LicenseInfo]:
        """
        Loads and validates a license file.
        Returns LicenseInfo on success, None if no license file found.
        Raises ValueError on invalid, expired, or machine-mismatched license.
        """
        license_path = path or os.getenv("COSTAFF_LICENSE_PATH") or cls.DEFAULT_PATH

        if not os.path.exists(license_path):
            logger.info("No license file found. Running on OSS Plan.")
            cls._license = None
            return None

        with open(license_path, "r") as f:
            raw = yaml.safe_load(f)

        data = raw.get("license", {})

        signature_b64 = data.get("signature")
        if not signature_b64:
            raise ValueError("License file is missing a signature.")

        # Verify Ed25519 signature
        try:
            pub_key = _load_public_key()
            sig_bytes = base64.b64decode(signature_b64)
            pub_key.verify(sig_bytes, _canonical(data))
        except InvalidSignature:
            raise ValueError("License signature is invalid. The license file may have been tampered with.")
        except Exception as e:
            raise ValueError(f"License verification failed: {e}")

        # Verify machine ID (if license is bound to a machine)
        licensed_machine = data.get("machine_id", "")
        if licensed_machine:
            current_machine = get_machine_id()
            if current_machine != licensed_machine:
                raise ValueError(
                    f"This license is bound to a different machine. "
                    f"Current machine ID: {current_machine}. "
                    "Please contact simonliuyuwei@gmail.com to transfer your license."
                )

        # Parse expiry
        expires_raw = data.get("expires_at")
        if expires_raw is not None and expires_raw != "null":
            if isinstance(expires_raw, str):
                expires_at = date.fromisoformat(expires_raw)
            elif isinstance(expires_raw, date):
                expires_at = expires_raw
            else:
                expires_at = None
        else:
            expires_at = None

        limits = data.get("limits", {})
        info = LicenseInfo(
            plan=data.get("plan", "enterprise"),
            issued_to=data.get("issued_to", "Unknown"),
            contact_phone=data.get("contact_phone", ""),
            expires_at=expires_at,
            limits={
                "max_agents": int(limits.get("max_agents", OSS_LIMITS["max_agents"])),
                "max_users":  int(limits.get("max_users",  OSS_LIMITS["max_users"])),
                "max_skills": int(limits.get("max_skills", OSS_LIMITS["max_skills"])),
            },
        )

        if info.is_expired:
            raise ValueError(
                f"License expired on {info.expires_at}. "
                "Please renew your license or revert to the OSS Plan."
            )

        logger.info(f"License loaded: issued_to={info.issued_to}, expires_at={info.expires_at}")
        cls._license = info
        return info

    @classmethod
    def get(cls) -> LicenseInfo:
        """
        Returns active LicenseInfo. Falls back to OSS limits if no valid license.
        Always call load() at startup; get() is for runtime limit checks.
        """
        if cls._license is not None:
            return cls._license
        return LicenseInfo(
            plan="oss",
            issued_to="OSS User",
            expires_at=None,
            limits=OSS_LIMITS.copy(),
        )

    @classmethod
    def check_agent_limit(cls, current_count: int) -> None:
        """Raises ValueError if adding one more agent would exceed the license limit."""
        limit = cls.get().max_agents
        if current_count >= limit:
            plan = cls.get().plan.upper()
            raise ValueError(
                f"Agent limit reached ({current_count}/{limit}) under the {plan} Plan. "
                "Please upgrade to add more agents."
            )

    @classmethod
    def check_user_limit(cls, db) -> None:
        """Raises ValueError if the total number of user profiles has reached the license limit."""
        from core.models import UserContact
        limit = cls.get().max_users
        count = db.query(UserContact).count()
        if count >= limit:
            plan = cls.get().plan.upper()
            raise ValueError(
                f"User limit reached ({count}/{limit}) under the {plan} Plan. "
                "Please upgrade to add more users."
            )

    @classmethod
    def check_skill_limit(cls, db) -> None:
        """Raises ValueError if the total number of Skill configs has reached the license limit."""
        from core.models import SkillConfig
        limit = cls.get().max_skills
        count = db.query(SkillConfig).count()
        if count >= limit:
            plan = cls.get().plan.upper()
            raise ValueError(
                f"Skill limit reached ({count}/{limit}) under the {plan} Plan. "
                "Please upgrade your plan to add more Skills."
            )
