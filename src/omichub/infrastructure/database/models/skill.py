"""Skill ORM 模型 — SKILL.md 标准技能（L1 元数据 + L2 正文缓存）

prompt 列保存 SKILL.md 正文（L2 指令，use_skill 按需加载）；
scripts/references/assets 落盘于 data/ai/skills/<skill_id>/（L3 按需读取）。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class SkillModel(Base, TimestampMixin):
    """技能表"""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 阿里云官方技能 ID 可达 60+ 字符（如 alibabacloud-tech-solution-*-auto-deploy），放宽到 100
    skill_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    icon: Mapped[str] = mapped_column(String(10), nullable=False, default="\U0001f527")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- SKILL.md 标准化字段（Part A 存储层） ---
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 来源类型：market / github / zip / json / builtin
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="json", server_default="json"
    )
    # 来源引用：GitHub 仓库 URL / 原始 JSON URL 等，用于"检查更新"
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 导入时的上游 commit / 分支快照，与 source_ref 配套做更新检测
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_scripts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 原始 frontmatter 全量留档
    frontmatter: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class SkillVersionModel(Base, TimestampMixin):
    """技能版本历史快照（每次内容变更留档，支撑回滚与审计）"""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "revision", name="uq_skill_versions_skill_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[str] = mapped_column(String(100), index=True)
    # 平台递增序号（1,2,3...）；version 是 SKILL.md frontmatter 声明版本的留档
    revision: Mapped[int] = mapped_column(Integer)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    name: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    tool_definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    icon: Mapped[str] = mapped_column(String(10), default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    frontmatter: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 快照来源：admin（手工更新）/ import（导入覆盖）/ rollback（回滚产生）
    source: Mapped[str] = mapped_column(String(20), default="admin")
    changelog: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class SkillInvocationModel(Base, TimestampMixin):
    """技能调用记录（Agent 加载技能时落库，供资源中心"最近调用/累计次数"与审计）"""

    __tablename__ = "skill_invocations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    skill_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 技能来源：market / github / zip / json / builtin / aliyun_official
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # 触发加载的工具：use_skill（L2 加载）/ skill_resource（L3 资源）
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False, default="use_skill")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
