"""AI 域仓储接口"""

from typing import Any, Protocol
from uuid import UUID

from omichub.domain.ai.entities import Conversation


class IConversationRepository(Protocol):
    """对话仓储接口"""

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None: ...

    async def list_by_user(self, user_id: UUID) -> list[Conversation]: ...

    async def save(self, conversation: Conversation) -> Conversation: ...

    async def delete(self, conversation_id: UUID) -> bool: ...

    async def append_message(self, conversation_id: UUID, message: dict[str, Any]) -> None: ...
