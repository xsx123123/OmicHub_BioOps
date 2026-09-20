"""AI Provider 配置仓储实现 - SQLAlchemy"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.security import decrypt_value, encrypt_value
from cygnusx.domain.ai_provider.entities import AIProviderConfig
from cygnusx.domain.ai_provider.repositories import IAIProviderConfigRepository
from cygnusx.domain.ai_provider.value_objects import ProviderType
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel


class SqlAlchemyAIProviderConfigRepository(IAIProviderConfigRepository):
    """AI Provider 配置仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, config_id: UUID) -> AIProviderConfig | None:
        model = await self._session.get(AIProviderConfigModel, config_id)
        return self._to_entity(model) if model else None

    async def get_default(self) -> AIProviderConfig | None:
        result = await self._session.execute(
            select(AIProviderConfigModel)
            .where(
                AIProviderConfigModel.is_default.is_(True),
                AIProviderConfigModel.is_active.is_(True),
            )
            .order_by(desc(AIProviderConfigModel.updated_at))
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_all(self, active_only: bool = False) -> list[AIProviderConfig]:
        query = select(AIProviderConfigModel)
        if active_only:
            query = query.where(AIProviderConfigModel.is_active.is_(True))
        query = query.order_by(
            desc(AIProviderConfigModel.is_default), desc(AIProviderConfigModel.updated_at)
        )
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def save(self, config: AIProviderConfig) -> AIProviderConfig:
        model = await self._session.get(AIProviderConfigModel, config.id)
        if model is None:
            model = self._to_model(config)
            self._session.add(model)
        else:
            self._update_model(model, config)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, config_id: UUID) -> bool:
        model = await self._session.get(AIProviderConfigModel, config_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def set_default(self, config_id: UUID) -> None:
        """将指定配置设为默认，并取消其他配置的默认状态"""
        await self._session.execute(
            select(AIProviderConfigModel).where(AIProviderConfigModel.is_default.is_(True))
        )
        result = await self._session.execute(select(AIProviderConfigModel))
        for model in result.scalars().all():
            model.is_default = model.id == config_id
        await self._session.flush()

    async def count(self) -> int:
        result = await self._session.execute(select(AIProviderConfigModel.id))
        return len(result.scalars().all())

    @staticmethod
    def _to_entity(model: AIProviderConfigModel) -> AIProviderConfig:
        return AIProviderConfig(
            id=model.id,
            name=model.name,
            provider_type=ProviderType(model.provider_type),
            model=model.model,
            base_url=model.base_url,
            api_key=decrypt_value(model.api_key),
            temperature=model.temperature,
            max_tokens=model.max_tokens,
            top_p=model.top_p,
            timeout=model.timeout,
            input_price=model.input_price,
            output_price=model.output_price,
            input_cache_price=model.input_cache_price,
            output_cache_price=model.output_cache_price,
            is_active=model.is_active,
            is_default=model.is_default,
            extra_params=model.extra_params or {},
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_model(config: AIProviderConfig) -> AIProviderConfigModel:
        return AIProviderConfigModel(
            id=config.id,
            name=config.name,
            provider_type=config.provider_type.value,
            model=config.model,
            base_url=config.base_url,
            api_key=encrypt_value(config.api_key),
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            timeout=config.timeout,
            input_price=config.input_price,
            output_price=config.output_price,
            input_cache_price=config.input_cache_price,
            output_cache_price=config.output_cache_price,
            is_active=config.is_active,
            is_default=config.is_default,
            extra_params=config.extra_params,
        )

    @staticmethod
    def _update_model(model: AIProviderConfigModel, config: AIProviderConfig) -> None:
        model.name = config.name
        model.provider_type = config.provider_type.value
        model.model = config.model
        model.base_url = config.base_url
        model.temperature = config.temperature
        model.max_tokens = config.max_tokens
        model.top_p = config.top_p
        model.timeout = config.timeout
        model.input_price = config.input_price
        model.output_price = config.output_price
        model.input_cache_price = config.input_cache_price
        model.output_cache_price = config.output_cache_price
        model.is_active = config.is_active
        model.is_default = config.is_default
        model.extra_params = config.extra_params
        # api_key 只在非空且不是 mask 占位时更新
        if config.api_key and config.api_key != "********":
            model.api_key = encrypt_value(config.api_key)
