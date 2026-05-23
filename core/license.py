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
from datetime import date, datetime, timedelta
from typing import Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# --- Public key (hardcoded — private key is kept by the licensor) ---
_PUBLIC_KEY_B64 = "L2TjTtry0aSRj9nEBXWZ7CwYRZHPn0teBVE5PgdWT2Y="

# Days after a license's issued_at that `costaff license apply` will still
# accept it. Enforced ONLY at activation (apply), never at runtime/load —
# once activated the license runs until expires_at. A stale/leaked license
# can therefore only be activated within this window of being issued.
ACTIVATION_WINDOW_DAYS = 30

# --- OSS Plan limits ---
OSS_LIMITS = {
    "max_agents": 3,
    "max_users":  1,
    "max_skills": 10,
}

# --- Upgrade pitch (shown when a limit is hit) ---
PRICING_URL = "https://costaffs.app/pricing"
CONTACT_EMAIL = "[email protected]"

_TIER_SUMMARY = {
    "max_agents": "Starter: 10  /  Pro: 25  /  Enterprise: unlimited",
    "max_users":  "Starter: 5   /  Pro: 20  /  Enterprise: unlimited",
    "max_skills": "Starter: 30  /  Pro: unlimited  /  Enterprise: unlimited",
}


def _upgrade_pitch(resource: str) -> str:
    """Compose a friendly upgrade message shown when an OSS/paid limit is hit.

    `resource` is one of: max_agents, max_users, max_skills.
    """
    return (
        f"\n\nUpgrade options ({resource.replace('max_', '')}):\n"
        f"  {_TIER_SUMMARY.get(resource, '')}\n"
        f"  → DIY License pricing: {PRICING_URL}\n"
        f"  → FDE / Premium Agents: {CONTACT_EMAIL}"
    )


def get_machine_id() -> str:
    """Hashed machine identifier — INFORMATIONAL ONLY.

    Machine binding is no longer enforced at load() / runtime (a deliberate
    posture: the container could never verify the host's identity without
    trusting an injectable env var). This is kept solely so
    `costaff license machine-id` can still display an id if a licensor
    wants it for their own records. macOS: IOPlatformUUID via ioreg;
    Linux: /etc/machine-id; SHA-256 hashed so the raw id is never exposed.
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
    # Path/mtime of the file that produced _license, so a freshly applied
    # license is picked up WITHOUT a restart (decision C: same-day effect).
    _loaded_path: Optional[str] = None
    _loaded_mtime: Optional[float] = None
    # True when a license file exists but is expired / tampered / bound to
    # another machine: we degrade to OSS and KEEP SERVING (never SystemExit),
    # but block real work if usage exceeds OSS limits (decisions A + B).
    _degraded: bool = False
    _degraded_reason: str = ""

    DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".costaff", "costaff-license.yaml")

    @staticmethod
    def check_activation_window(issued_at_raw) -> None:
        """Raise ValueError if today is more than ACTIVATION_WINDOW_DAYS
        past the license's issued_at. Call this ONLY from
        `costaff license apply` — never from load() — so an activated
        license keeps running until expires_at regardless of issue age.
        """
        if issued_at_raw is None or issued_at_raw == "null":
            raise ValueError("License is missing issued_at; cannot activate.")
        if isinstance(issued_at_raw, date):
            issued = issued_at_raw
        else:
            try:
                issued = date.fromisoformat(str(issued_at_raw).strip())
            except ValueError:
                raise ValueError(
                    f"License issued_at is not a valid date: {issued_at_raw!r}"
                )
        deadline = issued + timedelta(days=ACTIVATION_WINDOW_DAYS)
        if date.today() > deadline:
            raise ValueError(
                f"Activation window expired: this license was issued on "
                f"{issued} and had to be activated within "
                f"{ACTIVATION_WINDOW_DAYS} days (by {deadline}). "
                "Request a freshly issued license from the licensor."
            )

    @classmethod
    def load(cls, path: Optional[str] = None) -> Optional[LicenseInfo]:
        """
        Loads and validates a license file.
        Returns LicenseInfo on success, None if no license file found.
        Raises ValueError on invalid, expired, or machine-mismatched license.
        """
        license_path = path or os.getenv("COSTAFF_LICENSE_PATH") or cls.DEFAULT_PATH

        # isfile (not exists): a docker bind-mount of a missing host file
        # materialises as an empty DIR, and the "no license" placeholder
        # mount is /dev/null (a char device) — both must degrade cleanly
        # to OSS, never crash yaml parsing.
        if not os.path.isfile(license_path):
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

        # Machine binding is intentionally NOT enforced here. The signed
        # `machine_id` field is left in _canonical() so existing licenses
        # still verify, but runtime trusts only signature + expiry. The
        # one-time-on-host control is the 7-day activation window enforced
        # at `costaff license apply` (see check_activation_window), NOT a
        # per-load machine check.

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

    @staticmethod
    def _oss() -> LicenseInfo:
        return LicenseInfo(
            plan="oss",
            issued_to="OSS User",
            expires_at=None,
            limits=OSS_LIMITS.copy(),
        )

    @classmethod
    def _reeval(cls) -> None:
        """Cheap real-time re-evaluation so expiry takes effect the same day
        and a freshly applied license is picked up without a restart
        (decision C). Never raises — degrades to OSS on any problem.

        Cost per call: one stat() + a date compare. The expensive
        signature verification only re-runs when the file mtime changed.
        """
        path = os.getenv("COSTAFF_LICENSE_PATH") or cls.DEFAULT_PATH
        try:
            mtime = os.path.getmtime(path) if os.path.exists(path) else None
        except OSError:
            mtime = None

        # File appeared / changed / disappeared since last load → reload.
        if mtime != cls._loaded_mtime or path != cls._loaded_path:
            cls._loaded_path = path
            cls._loaded_mtime = mtime
            try:
                cls.load(path)
                cls._degraded = False
                cls._degraded_reason = ""
            except ValueError as e:
                cls._license = None
                cls._degraded = True
                cls._degraded_reason = str(e)
            return

        # Same file as before: only the date may have moved past expiry.
        if cls._license is not None and cls._license.is_expired:
            cls._degraded = True
            cls._degraded_reason = f"License expired on {cls._license.expires_at}."
            cls._license = None

    @classmethod
    def get(cls) -> LicenseInfo:
        """
        Returns the effective LicenseInfo for runtime limit checks.
        Re-evaluates expiry/file changes in real time, then falls back to
        OSS limits if there is no valid license. Never raises.
        """
        cls._reeval()
        if cls._license is not None:
            return cls._license
        return cls._oss()

    @classmethod
    def is_degraded(cls) -> bool:
        """True when a license file exists but is unusable (expired /
        tampered / wrong machine). Distinct from 'no license at all'."""
        cls._reeval()
        return cls._degraded

    @classmethod
    def usage_gate(cls, usage: dict) -> Optional[str]:
        """Runtime work gate (decisions A + B).

        When running on effective OSS limits — whether because the license
        is degraded (expired/tampered/wrong-machine) OR there is simply no
        paid license — any resource count that EXCEEDS the OSS limit blocks
        real work. Returns a user-facing denial string, or None to allow.

        A *valid* paid license within its own limits never trips this gate
        (paid limits are enforced only at creation, as before).
        """
        info = cls.get()
        if info.plan != "oss":
            return None
        over = []
        if usage.get("agents", 0) > OSS_LIMITS["max_agents"]:
            over.append(f"agents {usage['agents']}/{OSS_LIMITS['max_agents']}")
        if usage.get("users", 0) > OSS_LIMITS["max_users"]:
            over.append(f"users {usage['users']}/{OSS_LIMITS['max_users']}")
        if usage.get("skills", 0) > OSS_LIMITS["max_skills"]:
            over.append(f"skills {usage['skills']}/{OSS_LIMITS['max_skills']}")
        if not over:
            return None
        reason = cls._degraded_reason or "No active license (OSS plan)."
        return (
            f"Service unavailable: {reason}\n\n"
            f"The system reverted to the free OSS plan, but current usage exceeds OSS limits: "
            f"{', '.join(over)}.\n\n"
            f"To continue:\n"
            f"  → Renew or upgrade your license: {PRICING_URL}\n"
            f"  → Contact us: {CONTACT_EMAIL}\n"
            f"  → Or reduce usage to OSS limits "
            f"(agents: {OSS_LIMITS['max_agents']}, "
            f"users: {OSS_LIMITS['max_users']}, "
            f"skills: {OSS_LIMITS['max_skills']})"
        )

    @classmethod
    def check_agent_limit(cls, current_count: int) -> None:
        """Raises ValueError if adding one more agent would exceed the license limit."""
        limit = cls.get().max_agents
        if current_count >= limit:
            plan = cls.get().plan.upper()
            raise ValueError(
                f"Agent limit reached ({current_count}/{limit}) under the {plan} plan."
                + _upgrade_pitch("max_agents")
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
                f"User limit reached ({count}/{limit}) under the {plan} plan."
                + _upgrade_pitch("max_users")
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
                f"Skill limit reached ({count}/{limit}) under the {plan} plan."
                + _upgrade_pitch("max_skills")
            )
