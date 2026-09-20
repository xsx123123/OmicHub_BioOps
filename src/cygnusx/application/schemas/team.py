"""团队空间 DTO"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TeamInfoDTO(BaseModel):
    """当前用户所属团队信息"""

    id: UUID
    name: str
    owner_id: UUID
    description: str | None = None
    role: str
    created_at: datetime
    updated_at: datetime


class TeamListResponse(BaseModel):
    """团队列表响应"""

    items: list[TeamInfoDTO] = []
    total: int = 0
