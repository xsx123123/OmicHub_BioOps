"""管理员维护的 AgentTeams Bridge 配置契约。"""

from pydantic import BaseModel, Field


class AgentTeamsBridgeConfigDTO(BaseModel):
    enabled: bool
    bridge_url: str
    timeout_seconds: float
    manager_token: str
    data_steward_token: str
    approval_token: str
    workflow_operator_token: str
    source: str
    configured: bool
    connected: bool = False


class AgentTeamsBridgeConfigUpdateDTO(BaseModel):
    enabled: bool
    bridge_url: str = Field(default="", max_length=512)
    timeout_seconds: float = Field(default=10.0, ge=1, le=120)
    manager_token: str = Field(default="", max_length=4096)
    data_steward_token: str = Field(default="", max_length=4096)
    approval_token: str = Field(default="", max_length=4096)
    workflow_operator_token: str = Field(default="", max_length=4096)


class AgentTeamsBridgeTokenBundleDTO(BaseModel):
    """One-time Worker credentials generated for an administrator to deploy."""

    manager_token: str
    data_steward_token: str
    approval_token: str
    workflow_operator_token: str


class AgentTeamsWorkerTokenIssueDTO(BaseModel):
    """Issue a revocable per-worker Bridge token (M6 credential convergence)."""

    identity: str = Field(min_length=1, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    note: str = Field(default="", max_length=256)
