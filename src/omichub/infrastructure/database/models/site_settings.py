"""站点设置 ORM 模型 — 单行配置（id 恒为 1）"""

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class SiteSettingModel(Base, TimestampMixin):
    """站点级全局设置（单行表，id 固定为 1）"""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    totp_policy: Mapped[str] = mapped_column(String(16), default="optional", nullable=False)
    # 对话内并行子 Agent fan-out 管理端开关（与 env SUBAGENT_FANOUT_ENABLED 任一为真即启用）
    subagent_fanout_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agentteams_chat_entry_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    collaboration_preset: Mapped[str] = mapped_column(String(16), default="custom", nullable=False)
    multi_expert_consultation_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    unified_intent_router_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Agent 长期记忆运行时总开关；默认 true 保持升级即现状。
    agent_memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    collaboration_degradation_locale: Mapped[str] = mapped_column(
        String(8), default="zh-CN", nullable=False
    )
    collaboration_degradation_template_zh: Mapped[str] = mapped_column(
        String(1_000), default="", nullable=False
    )
    collaboration_degradation_template_en: Mapped[str] = mapped_column(
        String(1_000), default="", nullable=False
    )
    home_quick_entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
