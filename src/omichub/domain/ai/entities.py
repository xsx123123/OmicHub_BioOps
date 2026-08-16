"""AI 域实体 - 聚合根"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.ai.value_objects import RoleType


class Message(BaseModel):
    """对话消息"""

    id: UUID
    role: RoleType
    content: str = ""
    tool_calls: list[dict[str, Any]] = []
    tool_call_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ContextWindow(BaseModel):
    """上下文窗口管理"""

    max_tokens: int = 8192
    messages: list[Message] = []
    summary: str = ""

    def truncate(self, max_messages: int = 20) -> list[Message]:
        """截断保留最近 N 条消息"""
        if len(self.messages) > max_messages:
            kept = self.messages[-max_messages:]
            self.messages = kept
        return self.messages


class Conversation(BaseModel):
    """对话聚合根"""

    id: UUID
    user_id: UUID
    title: str = "新对话"
    model: str = ""
    assistant_id: str | None = None
    context_window: ContextWindow = Field(default_factory=ContextWindow)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_message(self, message: Message) -> None:
        self.context_window.messages.append(message)
        self.updated_at = datetime.now()
