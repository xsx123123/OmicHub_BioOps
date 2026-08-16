"""Agent 长期记忆 API DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from omichub.application.schemas.base import OmicsHubBaseSchema

MemoryScope = Literal["profile", "project", "preference", "summary"]


class AgentMemoryDTO(OmicsHubBaseSchema):
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


class AgentMemoryClearResponse(OmicsHubBaseSchema):
    cleared_count: int
