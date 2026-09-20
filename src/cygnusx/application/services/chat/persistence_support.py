"""聊天流式请求的持久化辅助逻辑。"""

from __future__ import annotations

import inspect
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatHandoffEventModel, ChatMessageModel
from cygnusx.infrastructure.database.session import get_session_factory


class ChatPersistenceSupport:
    """封装流式聊天必须跨请求事务保存的记录。"""

    async def _commit_stream_anchor(self) -> None:
        """提交流式对话中不可丢失的关键锚点，后续生成继续使用新事务。"""
        commit = getattr(self._db, "commit", None)
        if not callable(commit):
            return
        result = commit()
        if inspect.isawaitable(result):
            await result

    async def _record_user_message_anchor(
        self,
        session_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageModel:
        """使用独立事务持久化用户消息，避免 SSE 断连回滚用户输入。"""
        if not isinstance(self._db, AsyncSession):
            message = await self.add_message(session_id, "user", content, metadata=metadata)
            await self._commit_stream_anchor()
            return message

        await self._commit_stream_anchor()
        async with get_session_factory()() as anchor_db:
            from cygnusx.application.services.chat_service import ChatService

            message = await ChatService(anchor_db).add_message(
                session_id,
                "user",
                content,
                metadata=metadata,
            )
            await anchor_db.commit()
        return message

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def get_handoff_events(
        self, session_id: str, user_id: str
    ) -> list[ChatHandoffEventModel]:
        """返回当前用户会话的 Handoff 审计链，不泄露其他用户事件。"""
        session = await self.get_session(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在或无权访问")
        result = await self._db.execute(
            select(ChatHandoffEventModel)
            .where(ChatHandoffEventModel.session_id == session_id)
            .order_by(ChatHandoffEventModel.hop_index)
        )
        return list(result.scalars().all())
