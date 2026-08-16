"""AI Provider 配置仓储接口"""

from typing import Protocol
from uuid import UUID

from omichub.domain.ai_provider.entities import AIProviderConfig


class IAIProviderConfigRepository(Protocol):
    """AI Provider 配置仓储接口"""

    async def get_by_id(self, config_id: UUID) -> AIProviderConfig | None: ...

    async def get_default(self) -> AIProviderConfig | None: ...

    async def list_all(self, active_only: bool = False) -> list[AIProviderConfig]: ...

    async def save(self, config: AIProviderConfig) -> AIProviderConfig: ...

    async def delete(self, config_id: UUID) -> bool: ...

    async def set_default(self, config_id: UUID) -> None: ...

    async def count(self) -> int: ...
