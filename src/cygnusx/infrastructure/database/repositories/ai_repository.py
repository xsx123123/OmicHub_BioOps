"""AI 域仓储实现 — SQLAlchemy"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.ai.entities import ContextWindow, Conversation, Message
from cygnusx.domain.ai.repositories import IConversationRepository
from cygnusx.domain.ai.value_objects import RoleType
from cygnusx.infrastructure.database.models.ai import ConversationModel, MessageModel


class SqlAlchemyConversationRepository(IConversationRepository):
    """对话仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        conv_model = await self._session.get(ConversationModel, conversation_id)
        if conv_model is None:
            return None
        result = await self._session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.timestamp)
        )
        messages = [
            Message(
                id=m.id,
                role=RoleType(m.role),
                content=m.content,
                tool_calls=m.tool_calls or [],
                tool_call_id=m.tool_call_id,
                timestamp=m.timestamp,
            )
            for m in result.scalars().all()
        ]
        return self._to_entity(conv_model, messages)

    async def list_by_user(self, user_id: UUID) -> list[Conversation]:
        result = await self._session.execute(
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(desc(ConversationModel.updated_at))
        )
        return [self._to_entity(m, []) for m in result.scalars().all()]

    async def save(self, conversation: Conversation) -> Conversation:
        # upsert 对话
        model = await self._session.get(ConversationModel, conversation.id)
        if model is None:
            model = ConversationModel(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                model=conversation.model,
                summary=conversation.context_window.summary,
                assistant_id=conversation.assistant_id,
            )
            self._session.add(model)
        else:
            model.title = conversation.title
            model.model = conversation.model
            model.summary = conversation.context_window.summary
            if conversation.assistant_id is not None:
                model.assistant_id = conversation.assistant_id
        await self._session.flush()

        # upsert 所有消息（按 id）
        for msg in conversation.context_window.messages:
            stmt = pg_insert(MessageModel).values(
                id=msg.id,
                conversation_id=conversation.id,
                role=msg.role.value,
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[MessageModel.id],
                set_={
                    "content": stmt.excluded.content,
                    "role": stmt.excluded.role,
                    "tool_calls": stmt.excluded.tool_calls,
                    "tool_call_id": stmt.excluded.tool_call_id,
                },
            )
            await self._session.execute(stmt)
        await self._session.flush()
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        model = await self._session.get(ConversationModel, conversation_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def append_message(self, conversation_id: UUID, message: dict[str, Any]) -> None:
        """追加单条消息（增量持久化）"""
        model = MessageModel(
            conversation_id=conversation_id,
            role=message.get("role", "user"),
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls", []),
            tool_call_id=message.get("tool_call_id"),
        )
        self._session.add(model)
        await self._session.flush()

    @staticmethod
    def _to_entity(m: ConversationModel, messages: list[Message]) -> Conversation:
        return Conversation(
            id=m.id,
            user_id=m.user_id,
            title=m.title,
            model=m.model,
            assistant_id=m.assistant_id,
            context_window=ContextWindow(messages=messages, summary=m.summary or ""),
            created_at=m.created_at,
            updated_at=m.updated_at or datetime.now(),
        )
