"""聊天助手的应用层门面。"""

from __future__ import annotations

import uuid

from cygnusx.application.schemas.chat import ChatAssistantDTO, UpdateAssistantRequest
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatAssistantModel


class ChatAssistantManagement:
    """将助手持久化服务暴露为聊天服务的兼容接口。"""

    @staticmethod
    async def init_builtin_assistants(self) -> None:
        await self._assistants.init_builtin()

    async def list_assistants(self, category: str | None = None) -> list[ChatAssistantDTO]:
        assistants = await self._assistants.list_active(category)
        return [self._to_ast_dto(assistant) for assistant in assistants]

    async def get_assistant(self, assistant_id: str) -> ChatAssistantModel | None:
        return await self._assistants.get(assistant_id)

    async def get_assistant_dto(self, assistant_id: str) -> ChatAssistantDTO:
        assistant = await self.get_assistant(assistant_id)
        if not assistant:
            raise NotFoundError("助手不存在")
        return self._to_ast_dto(assistant)

    async def create_custom_assistant(
        self,
        user_id: str,
        assistant_id: str,
        name: str,
        description: str,
        system_prompt: str,
        default_model_id: uuid.UUID | None = None,
        default_temperature: float = 0.3,
        default_max_tokens: int = 65536,
        icon: str = "🤖",
        color: str = "#4f8ef7",
        category: str = "general",
    ) -> ChatAssistantDTO:
        assistant = await self._assistants.create(
            user_id=user_id,
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
        )
        return self._to_ast_dto(assistant)

    async def list_all_assistants(self) -> list[ChatAssistantDTO]:
        """列出所有助手（含停用，供管理员）。"""
        assistants = await self._assistants.list_all()
        return [self._to_ast_dto(assistant) for assistant in assistants]

    async def update_assistant(
        self, assistant_id: str, req: UpdateAssistantRequest
    ) -> ChatAssistantDTO:
        assistant = await self._assistants.update(assistant_id, req.model_dump(exclude_unset=True))
        return self._to_ast_dto(assistant)

    async def delete_assistant(self, assistant_id: str) -> bool:
        return await self._assistants.delete(assistant_id)

    async def toggle_assistant(self, assistant_id: str) -> ChatAssistantDTO:
        assistant = await self._assistants.toggle(assistant_id)
        return self._to_ast_dto(assistant)

    async def set_default_assistant(self, assistant_id: str) -> None:
        await self._assistants.set_default(assistant_id)
