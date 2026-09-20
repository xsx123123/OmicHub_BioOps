"""聊天会话与消息持久化服务。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel


def _strip_pg_unsafe_text(value: Any) -> Any:
    """递归剥离 PostgreSQL text/jsonb 无法存储的 NUL 字符（\\x00）。

    模型输出或工具结果可能夹带 NUL（二进制片段、终端控制序列等），asyncpg 遇到
    会抛 UntranslatableCharacterError 并回滚整个事务，导致整轮回复丢失；
    落库前统一剥离，仅影响不可存储字符，不改变正常内容。
    """
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {key: _strip_pg_unsafe_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_pg_unsafe_text(item) for item in value]
    return value


class SessionService:
    """集中处理会话与消息 CRUD，不承载 Runtime 编排。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        on_message_added: Callable[[ChatSessionModel], Awaitable[None]] | None = None,
    ) -> None:
        self._db = db
        self._on_message_added = on_message_added

    async def create(
        self,
        *,
        user_id: str,
        model_id: uuid.UUID,
        title: str,
        assistant_id: str | None,
        agent_id: str | None,
        mode: str,
        workspace_id: str | None,
        sandbox_meta: dict[str, Any] | None,
        project_id: str | None,
    ) -> ChatSessionModel:
        session = ChatSessionModel(
            id=uuid.uuid4(),
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=project_id,
            model_id=model_id,
            title=title,
            assistant_id=assistant_id,
            agent_id=agent_id,
            status="active",
            mode=mode,
            sandbox_meta=sandbox_meta,
            workspace_id=workspace_id,
        )
        if mode == "studio" and not session.workspace_id:
            session.workspace_id = session.session_id
        self._db.add(session)
        await self._db.flush()
        return session

    async def get(self, session_id: str, user_id: str) -> ChatSessionModel | None:
        result = await self._db.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
                ChatSessionModel.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        user_id: str,
        mode: str | None,
        *,
        limit: int,
        offset: int,
        status: str = "active",
        project_id: str | None = None,
    ) -> list[ChatSessionModel]:
        query = select(ChatSessionModel).where(
            ChatSessionModel.user_id == user_id, ChatSessionModel.status == status
        )
        if mode is not None:
            query = query.where(ChatSessionModel.mode == mode)
        if project_id is not None:
            query = query.where(ChatSessionModel.project_id == project_id)
        result = await self._db.execute(
            query.order_by(desc(ChatSessionModel.updated_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        content_type: str,
        status: str,
        metadata: dict[str, Any] | None,
    ) -> ChatMessageModel:
        message = ChatMessageModel(
            id=uuid.uuid4(),
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=_strip_pg_unsafe_text(content),
            content_type=content_type,
            status=status,
            metadata_json=_strip_pg_unsafe_text(metadata or {}),
        )
        self._db.add(message)
        result = await self._db.execute(
            select(ChatSessionModel)
            .where(ChatSessionModel.session_id == session_id)
            .execution_options(populate_existing=True)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            session.message_count += 1
            session.last_message_at = datetime.now(UTC)
            session.updated_at = datetime.now(UTC)
            if self._on_message_added is not None:
                await self._on_message_added(session)
        await self._db.flush()
        return message

    async def update_message_content(
        self,
        *,
        message_id: str,
        content: str,
        status: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        result = await self._db.execute(
            select(ChatMessageModel).where(ChatMessageModel.message_id == message_id)
        )
        message = result.scalar_one_or_none()
        if message is None:
            return
        message.content = _strip_pg_unsafe_text(content)
        message.status = status
        if metadata:
            message.metadata_json = _strip_pg_unsafe_text(
                {**(message.metadata_json or {}), **metadata}
            )
        await self._db.flush()

    async def get_messages(self, session_id: str) -> list[ChatMessageModel]:
        result = await self._db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        )
        return list(result.scalars().all())
