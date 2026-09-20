"""AI Provider 配置应用服务"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import anyio
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.ai_provider import (
    AIProviderConfigCreateDTO,
    AIProviderConfigDTO,
    AIProviderConfigTestResponse,
    AIProviderConfigUpdateDTO,
    AIProviderDiscoverResponse,
    AIProviderTemplate,
    DiscoveredModel,
)
from cygnusx.application.services.ai_provider_yaml_writer import AIProviderYamlWriter
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.domain.ai_provider.entities import AIProviderConfig
from cygnusx.domain.ai_provider.services import AIProviderConfigDomainService
from cygnusx.domain.ai_provider.value_objects import ProviderType
from cygnusx.infrastructure.ai_provider.litellm_provider import LiteLLMProvider
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    OpenAICompatibleProvider,
    provider_manager,
)
from cygnusx.infrastructure.database.repositories.ai_provider_repository import (
    SqlAlchemyAIProviderConfigRepository,
)

# API Key 脱敏哨兵：GET 接口回显用，PUT 接口据此判断是否保留原值。
# 与仓储层 ai_provider_repository._update_model 的守卫保持一致，形成双重防护。
MASKED_API_KEY = "********"


def _to_dto(config: AIProviderConfig) -> AIProviderConfigDTO:
    return AIProviderConfigDTO(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type.value,
        model=config.model,
        base_url=config.base_url,
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
        # 已配置则回显脱敏哨兵，前端据此判断是否已设密钥；
        # 回传时哨兵与空串都视为"不更新"，绝不覆写真实 Key。
        api_key=MASKED_API_KEY if config.api_key else "",
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


class AIProviderConfigService:
    """AI Provider 配置应用服务"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemyAIProviderConfigRepository(db)
        self._domain = AIProviderConfigDomainService(self._repo)
        self._yaml_writer = AIProviderYamlWriter()

    async def _persist_to_yaml(self) -> None:
        """写操作后把 DB 当前全量 Provider 回写 YAML（key 写 ${ENV_KEY} 占位）。

        YAML 为单一事实源：网页端改动经此回写落盘，下次启动 loader 即据此 prune DB，
        形成「yaml 优先 + 网页可改且自动回写」闭环。
        """
        configs = await self._repo.list_all()
        self._yaml_writer.write_configs(configs)

    async def list_configs(self) -> list[AIProviderConfigDTO]:
        configs = await self._repo.list_all()
        return [_to_dto(c) for c in configs]

    async def list_templates(self) -> list[AIProviderTemplate]:
        """加载内置 Provider 模板，并标记是否已在数据库中存在。"""
        settings = get_settings()
        path = anyio.Path(settings.ai_provider_config_yaml or "data/ai/provider_templates.yaml")
        fallback = anyio.Path("data/ai/provider_templates.yaml")
        if not await path.exists():
            path = fallback
        templates: list[dict[str, Any]] = []
        if await path.exists():
            async with await anyio.open_file(path, encoding="utf-8") as f:
                content = await f.read()
            data = yaml.safe_load(content) or {}
            templates = data.get("templates", [])
        existing_names = {c.name for c in await self._repo.list_all()}
        result: list[AIProviderTemplate] = []
        for item in templates:
            name = item.get("name", "")
            if not name:
                continue
            env_key = item.get("env_key", "")
            result.append(
                AIProviderTemplate(
                    name=name,
                    provider_type=item.get("provider_type", "openai_compatible"),
                    base_url=item.get("base_url", ""),
                    default_models=item.get("default_models", []),
                    env_key=env_key,
                    exists=name in existing_names,
                )
            )
        return result

    async def get_config(self, config_id: UUID) -> AIProviderConfigDTO:
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise NotFoundError("AI Provider 配置不存在")
        return _to_dto(config)

    async def create_config(self, dto: AIProviderConfigCreateDTO) -> AIProviderConfigDTO:
        config = AIProviderConfig.create(
            name=dto.name,
            provider_type=ProviderType(dto.provider_type),
            model=dto.model,
            base_url=dto.base_url,
            api_key=dto.api_key,
            temperature=dto.temperature,
            max_tokens=dto.max_tokens,
            top_p=dto.top_p,
            timeout=dto.timeout,
            input_price=dto.input_price,
            output_price=dto.output_price,
            input_cache_price=dto.input_cache_price,
            output_cache_price=dto.output_cache_price,
            extra_params=dto.extra_params,
        )
        self._domain.validate(config)
        config = await self._domain.prepare_new_default(config)
        config = await self._repo.save(config)
        await self._persist_to_yaml()
        provider_manager.clear_cache(str(config.id))
        return _to_dto(config)

    async def update_config(
        self, config_id: UUID, dto: AIProviderConfigUpdateDTO
    ) -> AIProviderConfigDTO:
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise NotFoundError("AI Provider 配置不存在")

        config.name = dto.name
        config.provider_type = ProviderType(dto.provider_type)
        config.model = dto.model
        config.base_url = dto.base_url
        config.temperature = dto.temperature
        config.max_tokens = dto.max_tokens
        config.top_p = dto.top_p
        config.timeout = dto.timeout
        config.input_price = dto.input_price
        config.output_price = dto.output_price
        config.input_cache_price = dto.input_cache_price
        config.output_cache_price = dto.output_cache_price
        config.is_active = dto.is_active
        config.extra_params = dto.extra_params
        # 仅当提交了非空、且非脱敏哨兵的 Key 时才更新；
        # 空串与 "********"（脱敏回显原样回传）均保留原值。
        if dto.api_key and dto.api_key != MASKED_API_KEY:
            config.api_key = dto.api_key
        config.mark_updated()

        self._domain.validate(config)
        config = await self._repo.save(config)
        await self._persist_to_yaml()
        provider_manager.clear_cache(str(config.id))
        return _to_dto(config)

    async def delete_config(self, config_id: UUID) -> dict[str, Any]:
        """删除 Provider 配置；被会话/Agent 引用时降级为软删除（停用）。

        chat_sessions.model_id / agent_templates.model_id 对 ai_provider_configs 有外键，
        直接硬删会触发 FK 违例（500）。引用中的配置保留行并置 is_active=False，
        既保证历史数据完整，也让其不再出现在可选模型中。
        """
        from sqlalchemy import func, select

        from cygnusx.infrastructure.database.models.agent import AgentTemplateModel
        from cygnusx.infrastructure.database.models.chat import ChatSessionModel

        session_refs = await self._db.execute(
            select(func.count())
            .select_from(ChatSessionModel)
            .where(ChatSessionModel.model_id == config_id)
        )
        agent_refs = await self._db.execute(
            select(func.count())
            .select_from(AgentTemplateModel)
            .where(AgentTemplateModel.model_id == config_id)
        )
        referenced = (session_refs.scalar_one() or 0) + (agent_refs.scalar_one() or 0) > 0

        if referenced:
            config = await self._repo.get_by_id(config_id)
            if config is None:
                return {"deleted": False, "soft_deleted": False}
            config.is_active = False
            config.mark_updated()
            await self._repo.save(config)
            await self._persist_to_yaml()
            provider_manager.clear_cache(str(config_id))
            return {"deleted": True, "soft_deleted": True}

        ok = await self._repo.delete(config_id)
        if ok:
            await self._persist_to_yaml()
            provider_manager.clear_cache(str(config_id))
        return {"deleted": ok, "soft_deleted": False}

    async def set_default(self, config_id: UUID) -> AIProviderConfigDTO:
        config = await self._domain.set_default(config_id)
        await self._persist_to_yaml()
        return _to_dto(config)

    async def test_config(self, config_id: UUID, message: str = "") -> AIProviderConfigTestResponse:
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise NotFoundError("AI Provider 配置不存在")
        try:
            provider = LiteLLMProvider(config)
            response = await provider.chat(
                messages=[{"role": "user", "content": message or "你好，请简要介绍一下自己。"}]
            )
            content = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "") or ""
            return AIProviderConfigTestResponse(success=True, response=str(content))
        except Exception as e:  # noqa: BLE001
            return AIProviderConfigTestResponse(success=False, error=str(e))

    async def discover_models(self, config_id: UUID) -> AIProviderDiscoverResponse:
        """自动发现指定 Provider 下的可用模型列表。"""
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise NotFoundError("AI Provider 配置不存在")
        if not config.model or not config.base_url:
            return AIProviderDiscoverResponse(
                provider_id=config_id, provider_name=config.name, models=[]
            )
        provider = OpenAICompatibleProvider(config)
        try:
            raw_models = await provider.list_models()
        except Exception as e:  # noqa: BLE001
            raise BusinessError(f"发现模型失败: {e}") from e
        return AIProviderDiscoverResponse(
            provider_id=config_id,
            provider_name=config.name,
            models=[
                DiscoveredModel(
                    id=m["id"],
                    name=m.get("name") or m["id"],
                    owned_by=m.get("owned_by", "unknown"),
                )
                for m in raw_models
            ],
        )

    async def get_active_default(self) -> AIProviderConfig | None:
        return await self._repo.get_default()
