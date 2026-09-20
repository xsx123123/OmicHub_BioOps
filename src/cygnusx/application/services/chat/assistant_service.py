"""聊天助手的持久化服务。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatAssistantModel


class AssistantService:
    """集中管理内置与自定义聊天助手，不参与聊天 Runtime 编排。"""

    def __init__(self, db: AsyncSession, builtin_configs: list[dict[str, Any]]) -> None:
        self._db = db
        self._builtin_configs = builtin_configs

    async def init_builtin(self) -> None:
        result = await self._db.execute(
            select(ChatAssistantModel).where(ChatAssistantModel.is_builtin == True)  # noqa: E712
        )
        if result.scalars().first():
            return
        for config in self._builtin_configs:
            self._db.add(ChatAssistantModel(is_builtin=True, is_active=True, **config))
        await self._db.flush()

    async def list_active(self, category: str | None = None) -> list[ChatAssistantModel]:
        await self.init_builtin()
        query = select(ChatAssistantModel).where(ChatAssistantModel.is_active == True)  # noqa: E712
        if category:
            query = query.where(ChatAssistantModel.category == category)
        result = await self._db.execute(query.order_by(ChatAssistantModel.created_at))
        return list(result.scalars().all())

    async def get(self, assistant_id: str) -> ChatAssistantModel | None:
        result = await self._db.execute(
            select(ChatAssistantModel).where(ChatAssistantModel.assistant_id == assistant_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: str,
        assistant_id: str,
        name: str,
        description: str,
        system_prompt: str,
        default_model_id: uuid.UUID | None,
        default_temperature: float,
        default_max_tokens: int,
        icon: str,
        color: str,
        category: str,
    ) -> ChatAssistantModel:
        if await self.get(assistant_id):
            raise BusinessError(f"助手 ID '{assistant_id}' 已存在")
        assistant = ChatAssistantModel(
            assistant_id=assistant_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            default_model_id=default_model_id,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
            icon=icon,
            color=color,
            category=category,
            is_builtin=False,
            is_active=True,
            created_by=user_id,
        )
        self._db.add(assistant)
        await self._db.flush()
        return assistant

    async def list_all(self) -> list[ChatAssistantModel]:
        await self.init_builtin()
        result = await self._db.execute(
            select(ChatAssistantModel).order_by(
                ChatAssistantModel.is_default.desc(), ChatAssistantModel.created_at
            )
        )
        return list(result.scalars().all())

    async def update(self, assistant_id: str, changes: dict[str, Any]) -> ChatAssistantModel:
        assistant = await self._require(assistant_id)
        if changes.get("is_default"):
            result = await self._db.execute(
                select(ChatAssistantModel).where(ChatAssistantModel.is_default == True)  # noqa: E712
            )
            for existing in result.scalars().all():
                existing.is_default = False
        for key, value in changes.items():
            setattr(assistant, key, value)
        await self._db.flush()
        return assistant

    async def delete(self, assistant_id: str) -> bool:
        assistant = await self._require(assistant_id)
        if assistant.is_builtin:
            assistant.is_active = False
        else:
            await self._db.delete(assistant)
        await self._db.flush()
        return True

    async def toggle(self, assistant_id: str) -> ChatAssistantModel:
        assistant = await self._require(assistant_id)
        assistant.is_active = not assistant.is_active
        await self._db.flush()
        return assistant

    async def set_default(self, assistant_id: str) -> None:
        assistant = await self._require(assistant_id)
        result = await self._db.execute(
            select(ChatAssistantModel).where(ChatAssistantModel.is_default == True)  # noqa: E712
        )
        for existing in result.scalars().all():
            existing.is_default = False
        assistant.is_default = True
        await self._db.flush()

    async def _require(self, assistant_id: str) -> ChatAssistantModel:
        assistant = await self.get(assistant_id)
        if assistant is None:
            raise NotFoundError("助手不存在")
        return assistant
