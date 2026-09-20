"""沙盒域实体"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cygnusx.domain.sandbox.value_objects import ExecutionStatus, SandboxStatus


class SandboxSession(BaseModel):
    """沙盒会话聚合根"""

    id: UUID
    user_id: UUID
    container_id: str | None = None
    container_name: str = ""
    status: SandboxStatus = SandboxStatus.CREATING
    language: str = "python"
    last_activity: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime | None = None

    def is_active(self) -> bool:
        return self.status in (SandboxStatus.READY, SandboxStatus.IDLE, SandboxStatus.EXECUTING)


class ExecutionResult(BaseModel):
    """代码执行结果"""

    execution_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    stdout: str = ""
    stderr: str = ""
    outputs: list[dict[str, Any]] = []  # display_data：{type: image/png|echarts|text, data}
    error: str | None = None
    duration_ms: int = 0
