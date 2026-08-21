"""Cherry Studio 架构聊天系统 Pydantic DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatAttachment(BaseModel):
    """聊天附件（多模态消息用）"""

    type: str = Field("file", description="附件类型或 MIME；目录使用 directory")
    url: str = ""
    name: str = ""
    mime_type: str = ""
    file_id: str = ""
    source: str = ""
    recursive: bool = False


class ChatStreamRequest(BaseModel):
    """流式聊天请求"""

    messages: list[dict[str, Any]] = Field(..., description="消息列表 [{role, content, metadata?}]")
    model_id: UUID | None = Field(None, description="使用的模型配置 ID（与 agent_id 至少传一个）")
    agent_id: str | None = Field(None, description="Agent ID：传入则走 Agent 调度中枢")
    session_id: str | None = Field(None, description="会话 ID，新建则传 null")
    assistant_id: str | None = Field(None, description="助手 ID")
    system_prompt: str | None = Field(None, description="自定义系统提示词")
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = Field(True, description="是否流式返回")
    attachments: list[ChatAttachment] = Field(
        default_factory=list, description="当前用户消息的附件"
    )
    enable_web_search: bool = Field(False, description="是否启用联网搜索")
    enable_code_execution: bool = Field(
        False, description="是否启用代码执行（仅前端 Pyodide，后端透传标记）"
    )
    deep_thinking: bool = Field(False, description="是否开启深度思考/推理模式")
    mode: str | None = Field(
        None,
        description="会话模式 chat/studio；新建会话时生效，已有会话以会话行 mode 为准",
    )
    project_id: str | None = Field(None, max_length=64, description="新建会话的项目边界")
    mcp_mode: Literal["off", "auto", "manual"] | None = None
    extra_mcp_servers: list[str] | None = Field(default=None)
    multi_agent: bool | None = Field(
        None,
        description="是否启用当前会话的 multi-agent 协作运行时；未传时沿用会话设置",
    )
    overdrive: bool | None = Field(
        None,
        description="是否启用会话级超频编排；未传时沿用会话设置",
    )
    extend_max_rounds: bool = Field(
        False,
        description="工具调用轮次上限扩展：False=100 轮，True=1000 轮（用户确认继续后由前端置位）",
    )


class ChatMessageDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    role: str
    content: str
    content_type: str = "text"
    status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    tokens: dict[str, Any] = Field(default_factory=dict)


class MessageFeedbackRequest(BaseModel):
    """消息点赞/点踩反馈请求。rating=none 表示撤销反馈。"""

    rating: Literal["like", "dislike", "none"]
    comment: str | None = Field(None, max_length=2000, description="点踩原因（可选）")


class ChatHandoffEventDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_agent_id: str
    target_agent_id: str
    reason: str
    handoff_summary: str
    user_intent: str
    artifacts: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    hop_index: int
    created_at: datetime


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


class ChatSessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    title: str
    title_locked: bool = False
    assistant_id: str | None = None
    agent_id: str | None = None
    project_id: str | None = None
    model_id: UUID
    message_count: int
    status: str
    mode: str = "chat"
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    mcp_mode: Literal["off", "auto", "manual"] = "auto"
    extra_mcp_servers: list[str] = Field(default_factory=list)
    multi_agent: bool = False
    overdrive: bool = False
    # L2→L4 升级状态（suggested/dismissed/upgraded，含 room_id 只读标记）；无升级为 None。
    agentteams_upgrade: dict[str, Any] | None = None


class ChatAssistantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assistant_id: str
    name: str
    description: str | None = None
    system_prompt: str
    default_model_id: UUID | None = None
    default_temperature: float
    default_max_tokens: int
    icon: str
    color: str
    category: str
    is_builtin: bool
    is_active: bool
    is_default: bool = False


class CreateSessionRequest(BaseModel):
    title: str | None = "新对话"
    assistant_id: str | None = None
    model_id: UUID
    project_id: str | None = Field(None, max_length=64)


class UpdateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=64)


class RejectOverdriveApprovalRequest(BaseModel):
    """超频普通聊天中拒绝一次 Worker 工具调用。"""

    reason: str | None = Field(None, max_length=2_000)


class OverdriveControlRequest(BaseModel):
    """运行中的超频链控制指令。"""

    action: Literal["pause", "resume", "skip", "terminate", "directive"]
    task_id: str | None = Field(None, max_length=128)
    directive: str | None = Field(None, max_length=4_000)


class OverdrivePlanDecisionRequest(BaseModel):
    """Bind a user's decision to one immutable overdrive plan snapshot."""

    command_id: str = Field(..., min_length=1, max_length=128)
    action: Literal["approve", "revise", "cancel"]
    plan_version: int = Field(..., ge=1)
    plan_hash: str = Field(..., pattern=r"^sha256:[a-f0-9]{64}$")
    feedback: str = Field("", max_length=4_000)


class OverdriveRunCommandRequest(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=128)
    action: Literal["pause", "resume", "terminate"]


class OverdriveBranchApprovalRequest(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=128)
    action: Literal["approve", "reject"]
    reason: str = Field("", max_length=2_000)


class AgentTeamsUpgradeDecisionRequest(BaseModel):
    """L2→L4 升级建议卡的用户决策：accept 创建协作室房间并移交上下文；dismiss 不再弹卡。"""

    action: Literal["accept", "dismiss"]
    suggestion_id: str | None = Field(None, max_length=64)


class ChatSearchContentMatchDTO(BaseModel):
    session_id: str
    title: str
    title_locked: bool = False
    agent_id: str | None = None
    model_id: UUID
    mode: str = "chat"
    message_id: str
    snippet: str
    created_at: datetime
    updated_at: datetime


class ChatSessionSearchDTO(BaseModel):
    title_matches: list[ChatSessionDTO] = Field(default_factory=list)
    content_matches: list[ChatSearchContentMatchDTO] = Field(default_factory=list)


class CreateAssistantRequest(BaseModel):
    assistant_id: str
    name: str
    description: str = ""
    system_prompt: str
    icon: str = "\U0001f916"
    color: str = "#4f8ef7"
    category: str = "general"
    default_temperature: float = 0.3
    default_max_tokens: int = 4096


class UpdateAssistantRequest(BaseModel):
    """更新助手请求"""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    icon: str | None = None
    color: str | None = None
    category: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
