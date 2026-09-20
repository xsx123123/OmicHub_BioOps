"""Agent 长期记忆 API DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema

MemoryScope = Literal["profile", "project", "preference", "summary"]


class AgentMemoryDTO(CygnusXBaseSchema):
    id: str
    agent_id: str | None = None
    project_id: str | None = None
    scope: MemoryScope
    content: str
    keywords: list[str] = Field(default_factory=list)
    source_session: str | None = None
    confidence: float = 1.0
    use_count: int = 0
    last_used_at: datetime | None = None
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentMemoryClearResponse(CygnusXBaseSchema):
    cleared_count: int


class MemoryBlockDTO(CygnusXBaseSchema):
    id: int
    agent_id: str
    block_name: str
    content: str
    char_limit: int
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryFactDTO(CygnusXBaseSchema):
    id: int
    agent_id: str
    scope: MemoryScope
    content: str
    keywords: list[str] = Field(default_factory=list)
    source_session_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.8
    status: str = "active"
    superseded_by: int | None = None
    created_at: datetime | None = None
    last_recalled_at: datetime | None = None


class MemoryBlockUpdateRequest(CygnusXBaseSchema):
    content: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class MemoryOverviewDTO(CygnusXBaseSchema):
    mode: Literal["legacy", "v2"]
    agent_ids: list[str] = Field(default_factory=list)
    blocks: list[MemoryBlockDTO] = Field(default_factory=list)
    facts: list[MemoryFactDTO] = Field(default_factory=list)
    legacy_memories: list[AgentMemoryDTO] = Field(default_factory=list)
