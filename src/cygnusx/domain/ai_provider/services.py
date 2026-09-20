"""AI Provider 配置域服务"""

from uuid import UUID

from cygnusx.domain.ai_provider.entities import AIProviderConfig
from cygnusx.domain.ai_provider.repositories import IAIProviderConfigRepository


class AIProviderConfigDomainService:
    """AI Provider 配置域服务 — 负责默认配置切换与基础校验"""

    def __init__(self, repo: IAIProviderConfigRepository):
        self._repo = repo

    async def set_default(self, config_id: UUID) -> AIProviderConfig:
        """将指定配置设为默认，同时取消其他配置的默认状态"""
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise ValueError("AI Provider 配置不存在")
        await self._repo.set_default(config_id)
        config.is_default = True
        return config

    def validate(self, config: AIProviderConfig) -> None:
        """基础校验：名称、模型不能为空；温度/top_p 在合理范围"""
        if not config.name or not config.name.strip():
            raise ValueError("名称不能为空")
        if not config.model or not config.model.strip():
            raise ValueError("模型不能为空")
        if not 0 <= config.temperature <= 2:
            raise ValueError("temperature 必须在 0-2 之间")
        if not 0 <= config.top_p <= 1:
            raise ValueError("top_p 必须在 0-1 之间")
        if config.max_tokens < 1:
            raise ValueError("max_tokens 必须大于 0")
        if config.timeout < 1:
            raise ValueError("timeout 必须大于 0")

    async def prepare_new_default(self, config: AIProviderConfig) -> AIProviderConfig:
        """新建配置时，若当前无其他配置，自动设为默认"""
        count = await self._repo.count()
        if count == 0:
            config.is_default = True
        return config
