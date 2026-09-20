"""AI 域服务 - 上下文管理、工具编排"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from cygnusx.domain.ai.entities import Conversation, Message
from cygnusx.domain.ai.repositories import IConversationRepository
from cygnusx.domain.ai.value_objects import RoleType


class AIDomainService:
    """AI 域服务 - 对话生命周期与上下文构建"""

    def __init__(self, repo: IConversationRepository):
        self._repo = repo

    async def create_conversation(
        self, user_id: UUID, title: str = "新对话", model: str = ""
    ) -> Conversation:
        """创建新对话（不含系统占位消息，系统提示在构建上下文时注入）"""
        conversation = Conversation(id=uuid4(), user_id=user_id, title=title, model=model)
        return await self._repo.save(conversation)

    async def append_user_message(self, conversation: Conversation, content: str) -> Conversation:
        conversation.add_message(Message(id=uuid4(), role=RoleType.USER, content=content))
        return await self._repo.save(conversation)

    async def append_assistant_message(
        self,
        conversation: Conversation,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Conversation:
        conversation.add_message(
            Message(
                id=uuid4(),
                role=RoleType.ASSISTANT,
                content=content,
                tool_calls=tool_calls or [],
            )
        )
        return await self._repo.save(conversation)

    async def append_tool_message(
        self, conversation: Conversation, tool_call_id: str, content: str
    ) -> Conversation:
        conversation.add_message(
            Message(id=uuid4(), role=RoleType.TOOL, content=content, tool_call_id=tool_call_id)
        )
        return await self._repo.save(conversation)

    async def build_context_messages(
        self, conversation: Conversation, system_prompt: str
    ) -> list[dict[str, str]]:
        """构建发送给 LLM 的消息列表（前置系统提示，跳过存储的系统占位）"""
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for msg in conversation.context_window.messages:
            if msg.role == RoleType.SYSTEM:
                continue
            messages.append({"role": msg.role.value, "content": msg.content})
        return messages

    async def compress_context(
        self, conversation: Conversation, max_messages: int = 20
    ) -> Conversation:
        """长对话上下文截断（保留最近 N 条）"""
        conversation.context_window.truncate(max_messages)
        conversation.updated_at = datetime.now()
        return await self._repo.save(conversation)
