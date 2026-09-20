"""工具调用上下文 — 仅供 builtin transport 内部传递。

包含用户身份、追踪信息和数据库会话；禁止序列化或透传给外部 MCP server。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession


class ToolInvocationContext(BaseModel):
    """builtin MCP 调用时的内部上下文。

    该对象包含数据库会话等不可序列化信息，必须仅在进程内使用。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    agent_id: str | None = None
    session_id: str
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    db: AsyncSession
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict, description="调用方扩展字段")

    def __serialize__(self) -> None:
        """显式阻止序列化；Pydantic 不会自动调用，但可作为安全声明。"""
        raise RuntimeError("ToolInvocationContext MUST NOT be serialized or passed to external MCP servers")

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """重写以拒绝直接序列化（含 db 字段）。"""
        raise RuntimeError(
            "ToolInvocationContext.model_dump() is disabled to prevent leaking db session. "
            "Use explicit accessor methods instead."
        )

    def to_safe_dict(self) -> dict[str, Any]:
        """返回不含 db 的安全字典，仅限 builtin handler 显式使用。"""
        return {
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "extra": self.extra,
        }
