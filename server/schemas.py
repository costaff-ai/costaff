from typing import Optional, List, Dict
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class ServiceActionRequest(BaseModel):
    action: str  # start, stop, restart


class AddMCPRequest(BaseModel):
    name: str
    config: Optional[Dict] = None
    is_external: bool = False
    url: Optional[str] = None


class RegularWorkCreateRequest(BaseModel):
    title: str
    spec: str
    cron: str
    agent_id: Optional[str] = "costaff_agent"
    channel: Optional[str] = None
    recipient: Optional[str] = None
    user_id: Optional[str] = None


class RegularWorkUpdateRequest(BaseModel):
    title: Optional[str] = None
    spec: Optional[str] = None
    cron: Optional[str] = None
    agent_id: Optional[str] = None
    channel: Optional[str] = None
    recipient: Optional[str] = None
    status: Optional[str] = None  # active / paused


class EpicCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    user_id: Optional[str] = None


class EpicUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # active / completed / archived


class StoryCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    priority: Optional[str] = "medium"
    user_id: Optional[str] = None


class ProjectTaskCreateRequest(BaseModel):
    epic_id: str
    title: str
    spec: Optional[str] = None
    story_id: Optional[str] = None
    assigned_agent: Optional[str] = None
    priority: Optional[str] = "medium"
    user_id: Optional[str] = None


class ProjectTaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    spec: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_agent: Optional[str] = None


class GatewayUpdateRequest(BaseModel):
    platform: str
    config: Dict


class ApiConfigCreateRequest(BaseModel):
    name: str
    url: str
    method: str = "GET"
    headers: Optional[Dict] = None  # Plain dict; will be encrypted before storage
    description: Optional[str] = None
    user_id: Optional[str] = None
    agent_ids: Optional[str] = None  # Comma-separated agent IDs or __all__


class ApiConfigUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    agent_ids: Optional[str] = None


class SkillConfigCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    tags: Optional[str] = None
    usage: Optional[str] = None
    user_id: Optional[str] = None
    agent_ids: Optional[str] = None  # Comma-separated agent IDs or __all__


class SkillConfigUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    usage: Optional[str] = None
    is_active: Optional[bool] = None
    agent_ids: Optional[str] = None


class AgentMCPConfigRequest(BaseModel):
    agent_id: str
    mcps: List[str]


class ExternalAgentAddRequest(BaseModel):
    name: str
    a2a_url: str
    description: Optional[str] = None


class ExternalAgentUpdateRequest(BaseModel):
    a2a_url: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
