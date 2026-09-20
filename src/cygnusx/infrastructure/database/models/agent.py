"""Agent 模板 ORM 模型 — 多智能体协作平台的「专家角色」

一个 Agent 把「系统设定 + 绑定模型 + 绑定 MCP 工具 + 绑定技能」打包，
供聊天调度中枢按 agent_id 组装出一次完整的 LLM 请求。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class AgentTemplateModel(Base, TimestampMixin):
    """Agent 模板表"""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        if self.description is None:
            self.description = ""
        if self.avatar is None:
            self.avatar = "\U0001f916"
        if self.color is None:
            self.color = "#4f8ef7"
        if self.category is None:
            self.category = "general"
        if self.model_name is None:
            self.model_name = ""
        if self.model_engine is None:
            self.model_engine = ""
        if self.system_prompt is None:
            self.system_prompt = ""
        if self.welcome_message is None:
            self.welcome_message = ""
        if self.mcp_ids is None:
            self.mcp_ids = []
        if self.skill_ids is None:
            self.skill_ids = []
        if self.features is None:
            self.features = {}
        if self.temperature is None:
            self.temperature = 0.7
        if self.max_tokens is None:
            self.max_tokens = 65536
        if self.is_builtin is None:
            self.is_builtin = False
        if self.is_active is None:
            self.is_active = True
        if self.is_default is None:
            self.is_default = False

    __tablename__ = "agent_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    avatar: Mapped[str] = mapped_column(String(10), default="\U0001f916", nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#4f8ef7", nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)

    # 绑定的真实模型配置（ai_provider_configs.id）
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_provider_configs.id"), nullable=True
    )
    # YAML 中写的模型名称（按 name 匹配 ai_provider_configs，便于调试）
    model_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    # 展示用模型引擎 label（从关联 provider config 动态解析）
    model_engine: Mapped[str] = mapped_column(String(100), default="", nullable=False)

    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    welcome_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # 绑定的 MCP server UUID 字符串列表 / 技能 id 列表
    mcp_ids: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    skill_ids: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    features: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict, nullable=False)

    # 统一功能开关：联网搜索 / 代码执行 / 文件上传 / 深度思考
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=65536, nullable=False)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", name="agent_templates_agent_id_key"),
        Index("idx_agent_templates_category", "category", "is_active"),
    )


class UserAgentCapabilityModel(Base, TimestampMixin):
    """用户对某个 Agent 的个人能力选择，不包含可编辑提示词。"""

    __tablename__ = "user_agent_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("agent_templates.agent_id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_provider_configs.id"), nullable=True
    )
    mcp_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    skill_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "agent_id", name="uq_user_agent_capabilities_user_agent"),
        Index("idx_user_agent_capabilities_agent", "agent_id"),
    )
