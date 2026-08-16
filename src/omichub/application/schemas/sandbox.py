"""沙盒 DTO"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from omichub.application.schemas.base import OmicsHubBaseSchema


class SandboxSessionDTO(OmicsHubBaseSchema):
    """沙盒会话"""

    id: UUID
    user_id: UUID
    container_id: str | None = None
    status: str = "creating"
    language: str = "python"
    last_activity: datetime
    created_at: datetime
    expires_at: datetime | None = None


class CreateSandboxDTO(OmicsHubBaseSchema):
    """创建沙盒会话"""

    language: str = "python"


class ExecuteCodeDTO(OmicsHubBaseSchema):
    """代码执行请求"""

    code: str
    timeout: int = 0  # 0 表示使用默认超时
