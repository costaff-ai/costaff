import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Integer
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

def generate_uuid():
    """Helper to generate standard UUID strings for primary keys."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Identity & Profile
# ---------------------------------------------------------------------------

class UserContact(Base):
    """Stores persistent metadata about the user."""
    __tablename__ = "user_contacts"

    user_id = Column(String, primary_key=True)
    chinese_name = Column(String, nullable=True)
    english_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    company_address = Column(String, nullable=True)
    tax_id = Column(String, nullable=True)
    personal_email = Column(String, nullable=True)
    company_phone = Column(String, nullable=True)
    mobile_phone = Column(String, nullable=True)
    employee_id = Column(String, nullable=True)
    note = Column(String, nullable=True)


class Contact(Base):
    """Represents entries in the user's personal address book."""
    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    company = Column(String, nullable=True)
    note = Column(String, nullable=True)


class IdentityMap(Base):
    """Security mapping between Session IDs and real platform IDs."""
    __tablename__ = "identity_maps"

    session_id = Column(String, primary_key=True)
    hashed_id = Column(String, nullable=False, index=True)
    real_id = Column(String, nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)
    active_session_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FileTask(Base):
    """Tracks asynchronous file processing jobs."""
    __tablename__ = "file_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    app_name = Column(String, default="costaff-agent")
    filename = Column(String, nullable=True)
    status = Column(String, default="parsing")
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------

class Reminder(Base):
    """
    Simple one-time scheduled message to the user.
    No cron, no agent work — just sends a message at run_at.
    Also used as a log for messages sent via send_message_now.
    """
    __tablename__ = "reminders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    app_name = Column(String, nullable=False)
    message = Column(String, nullable=False)
    run_at = Column(DateTime, nullable=True)
    channel = Column(String, nullable=False)
    recipient = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending / sent / failed
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Regular Work — recurring scheduled agent jobs
# ---------------------------------------------------------------------------

class RegularWork(Base):
    """
    Recurring scheduled work delegated to an Agent.
    Replaces cron-based Task usage. Each active entry runs on its cron schedule.
    """
    __tablename__ = "regular_works"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    spec = Column(String, nullable=False)       # Full instructions for the Agent
    cron = Column(String, nullable=False)
    agent_id = Column(String, nullable=True)    # Which agent to call (None = costaff_agent)
    channel = Column(String, nullable=True)
    recipient = Column(String, nullable=True)
    status = Column(String, default="active")   # active / paused
    silent = Column(Boolean, default=False)     # True = internal only, skip user notification
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RegularWorkLog(Base):
    """Stores execution history for each RegularWork run."""
    __tablename__ = "regular_work_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    regular_work_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)     # success / failed
    output = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Project Management — Epic / Story / Task / TaskComment
# ---------------------------------------------------------------------------

class Epic(Base):
    """
    Top-level project container. Represents a long-term goal or initiative.
    Examples: 'Expense tracker', 'costaff development', 'Health monitor'
    """
    __tablename__ = "epics"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="active")   # active / completed / archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Story(Base):
    """
    A milestone or feature within an Epic.
    Represents a logical chunk of work with a clear completion condition.
    """
    __tablename__ = "stories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    epic_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="open")     # open / in_progress / done
    priority = Column(String, default="medium") # high / medium / low
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectTask(Base):
    """
    Atomic unit of work within a Story (or directly under an Epic).
    Agents execute tasks, update status, and leave comments when done.
    Supports queue-based ordering per agent, and optional cron scheduling.
    """
    __tablename__ = "project_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    epic_id = Column(String(36), nullable=False, index=True)
    story_id = Column(String(36), nullable=True, index=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    spec = Column(String, nullable=True)            # Full instructions for the Agent
    type = Column(String, default="immediate")       # immediate / scheduled
    assigned_agent = Column(String, nullable=True)   # e.g. "coding_agent"
    status = Column(String, default="backlog")       # backlog / queued / doing / done / failed
    priority = Column(String, default="medium")      # high / medium / low
    queue_order = Column(Integer, nullable=True)     # Position in the agent's queue
    depends_on = Column(String(36), nullable=True)   # task_id this task depends on
    cron = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    recipient = Column(String, nullable=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskComment(Base):
    """
    Immutable log entry on a ProjectTask.
    Written by Agents after execution or by users for context.
    Never deleted — forms the permanent history of a task.
    """
    __tablename__ = "task_comments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String, nullable=False)
    author = Column(String, nullable=False)         # "user" or agent_name
    content = Column(String, nullable=False)
    type = Column(String, default="note")            # result / decision / issue / note
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Diary — daily standup log per Agent
# ---------------------------------------------------------------------------

class Diary(Base):
    """
    Daily work journal written by each Agent at end-of-day.
    Structured as a standup: done / blocker / next.
    Accumulated into weekly and monthly summaries.
    """
    __tablename__ = "diary"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=False)      # Which agent wrote this
    date = Column(String, nullable=False)             # YYYY-MM-DD
    type = Column(String, default="daily")            # daily / weekly / monthly
    done = Column(String, nullable=True)              # What was completed
    blocker = Column(String, nullable=True)           # Issues encountered (null if none)
    next = Column(String, nullable=True)              # Planned next actions
    ref_task_ids = Column(String, nullable=True)      # JSON array of related ProjectTask IDs
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# External APIs & Skills
# ---------------------------------------------------------------------------

class ApiConfig(Base):
    """User-defined external API configurations callable by the Agent."""
    __tablename__ = "api_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, nullable=False, default="GET")
    headers_encrypted = Column(String, nullable=True)
    description = Column(String, nullable=True)
    user_id = Column(String, nullable=False, index=True)
    agent_ids = Column(String, nullable=True, default="__all__")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillConfig(Base):
    """User-defined Skills: reusable capabilities the Agent can discover and invoke."""
    __tablename__ = "skill_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    tags = Column(String, nullable=True)
    usage = Column(String, nullable=True)
    user_id = Column(String, nullable=False, index=True)
    agent_ids = Column(String, nullable=True, default="__all__")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
