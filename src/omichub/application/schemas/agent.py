"""Agent 模板 DTO — 多智能体协作平台资产"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _empty_str_to_none(value: Any) -> Any:
    """把空字符串转换成 None，避免前端清空选择时传 '' 导致 UUID 校验失败。"""
    if value == "":
        return None
    return value


EmptyStrUUID = Annotated[UUID | None, BeforeValidator(_empty_str_to_none)]

USER_AGENT_FEATURE_KEYS = frozenset({
    "enable_web_search",
    "enable_file_upload",
    "enable_code_execution",
    "enable_deep_thinking",
})


class AgentTemplateDTO(BaseModel):
    """Agent 模板（前台集市 + 后台编排共用）"""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    project_id: str | None = None
    name: str
    description: str = ""
    avatar: str = "\U0001f916"
    color: str = "#4f8ef7"
    category: str = "general"
    model_id: EmptyStrUUID = None
    model_name: str = ""
    model_engine: str = ""
    system_prompt: str = ""
    welcome_message: str = ""
    mcp_ids: list[Any] = Field(default_factory=list)
    skill_ids: list[Any] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 4096
    is_builtin: bool = False
    is_active: bool = True
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateAgentRequest(BaseModel):
    agent_id: str = ""
    project_id: str | None = Field(None, max_length=64)
    name: str
    description: str = ""
    avatar: str = "\U0001f916"
    color: str = "#4f8ef7"
    category: str = "general"
    model_id: EmptyStrUUID = None
    system_prompt: str = ""
    welcome_message: str = ""
    mcp_ids: list[Any] = Field(default_factory=list)
    skill_ids: list[Any] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 4096
    is_active: bool = True
    is_default: bool = False


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    project_id: str | None = Field(None, max_length=64)
    description: str | None = None
    avatar: str | None = None
    color: str | None = None
    category: str | None = None
    model_id: EmptyStrUUID = None
    system_prompt: str | None = None
    welcome_message: str | None = None
    mcp_ids: list[Any] | None = None
    skill_ids: list[Any] | None = None
    features: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class UserAgentCapabilityRequest(BaseModel):
    """用户为某个 Agent 选择的运行时能力；系统提示词始终由管理员维护。"""

    model_config = ConfigDict(extra="forbid")

    model_id: EmptyStrUUID = None
    mcp_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    features: dict[str, bool] = Field(default_factory=dict)


class UserAgentCapabilityDTO(UserAgentCapabilityRequest):
    agent_id: str
    is_customized: bool = False


class UserSelectableMCPDTO(BaseModel):
    """普通用户可为 Agent 选择的 MCP 摘要；不暴露服务连接配置。"""

    id: UUID
    name: str
    description: str = ""
    status: str = "offline"
    tool_count: int = 0
