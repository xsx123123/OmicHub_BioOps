"""Skill 域实体"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Skill(BaseModel):
    """技能实体 — SKILL.md 标准能力包（L1 元数据 + L2 正文 prompt）"""

    id: UUID
    skill_id: str
    name: str
    description: str = ""
    prompt: str = ""
    tool_definition: dict[str, Any] | None = None
    icon: str = "\U0001f527"
    category: str = "general"
    is_active: bool = True
    is_builtin: bool = False
    version: str | None = None
    author: str | None = None
    source_type: str = "json"
    source_ref: str | None = None
    source_commit: str | None = None
    has_scripts: bool = False
    frontmatter: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
