"""AI Copilot DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from cygnusx.application.schemas.base import CygnusXBaseSchema


class MessageDTO(CygnusXBaseSchema):
    """对话消息"""

    id: UUID
    role: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = []
    tool_call_id: str | None = None
    timestamp: datetime


class ConversationDTO(CygnusXBaseSchema):
    """对话摘要"""

    id: UUID
    user_id: UUID
    title: str = "新对话"
    model: str = ""
    assistant_id: str | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationDetailDTO(ConversationDTO):
    """对话详情（含消息）"""

    messages: list[MessageDTO] = []


class CreateConversationDTO(CygnusXBaseSchema):
    """创建对话请求"""

    title: str = "新对话"
    model: str = ""
    assistant_id: str | None = None
    assistant_id: str | None = None
    assistant_id: str | None = None
    assistant_id: str | None = None


class SendChatDTO(CygnusXBaseSchema):
    """发送对话（REST 回退用，主通道为 WebSocket）"""

    conversation_id: UUID
    content: str


class ToolCallResultDTO(CygnusXBaseSchema):
    """工具调用结果"""

    tool: str
    arguments: dict[str, Any] = {}
    result: Any = None
    success: bool = True
