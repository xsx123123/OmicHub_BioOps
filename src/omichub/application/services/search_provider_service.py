"""联网搜索服务商配置与执行服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.search_provider import (
    SearchProviderAvailabilityDTO,
    SearchProviderDTO,
    SearchProviderTestResponse,
    SearchProviderUpdateDTO,
)
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.core.security import decrypt_value, encrypt_value
from omichub.infrastructure.database.models.search_provider import SearchProviderConfigModel
from omichub.infrastructure.web_search.service import WebSearchResult, WebSearchService

MASKED_API_KEY = "********"

SEARCH_PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "tavily": {"name": "Tavily", "provider_type": "api", "base_url": "https://api.tavily.com", "key_url": "https://app.tavily.com/home", "is_local": False},
    "bocha": {"name": "Bocha", "provider_type": "api", "base_url": "https://api.bochaai.com/v1/web-search", "key_url": "https://open.bochaai.com/", "is_local": False},
    "zhipu": {"name": "智谱 Zhipu", "provider_type": "api", "base_url": "https://open.bigmodel.cn/api/paas/v4/web_search", "key_url": "https://open.bigmodel.cn/", "is_local": False},
    "exa": {"name": "Exa", "provider_type": "api", "base_url": "https://api.exa.ai", "key_url": "https://dashboard.exa.ai/api-keys", "is_local": False},
    "searxng": {"name": "SearXNG 自建", "provider_type": "searxng", "base_url": "", "key_url": "https://docs.searxng.org/", "is_local": False},
    "google": {"name": "Google", "provider_type": "scrape", "base_url": "", "key_url": "", "is_local": True},
    "bing": {"name": "Bing", "provider_type": "scrape", "base_url": "", "key_url": "", "is_local": True},
    "baidu": {"name": "Baidu", "provider_type": "scrape", "base_url": "", "key_url": "", "is_local": True},
}


class SearchProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _masked_api_key(value: str) -> str:
        if not value:
            return ""
        try:
            plain_value = decrypt_value(value)
        except Exception:  # noqa: BLE001
            return MASKED_API_KEY
        if len(plain_value) <= 8:
            return MASKED_API_KEY
        return f"{plain_value[:3]}****{plain_value[-4:]}"

    @staticmethod
    def _dto(model: SearchProviderConfigModel | None, preset_id: str) -> SearchProviderDTO:
        preset = SEARCH_PROVIDER_PRESETS[preset_id]
        return SearchProviderDTO(
            id=preset_id,
            name=preset["name"],
            provider_type=preset["provider_type"],
            api_key=SearchProviderService._masked_api_key(model.api_key) if model else "",
            base_url=model.base_url if model else preset["base_url"],
            is_enabled=model.is_enabled if model else False,
            is_default=model.is_default if model else False,
            params=model.params if model else {"maxResults": 5, "searchDepth": "basic"},
            timeout_seconds=model.timeout_seconds if model else 10,
            key_url=preset["key_url"],
            is_local=preset["is_local"],
            updated_at=model.updated_at if model else None,
        )

    async def _models(self) -> dict[str, SearchProviderConfigModel]:
        result = await self._db.execute(select(SearchProviderConfigModel))
        return {model.id: model for model in result.scalars().all()}

    async def list_providers(self) -> list[SearchProviderDTO]:
        models = await self._models()
        return [self._dto(models.get(provider_id), provider_id) for provider_id in SEARCH_PROVIDER_PRESETS]

    async def update_provider(self, provider_id: str, dto: SearchProviderUpdateDTO) -> SearchProviderDTO:
        preset = SEARCH_PROVIDER_PRESETS.get(provider_id)
        if not preset:
            raise NotFoundError("搜索服务商不存在")
        model = await self._db.get(SearchProviderConfigModel, provider_id)
        if model is None:
            model = SearchProviderConfigModel(id=provider_id, name=preset["name"], provider_type=preset["provider_type"])
            self._db.add(model)
        if dto.api_key and dto.api_key != MASKED_API_KEY:
            model.api_key = encrypt_value(dto.api_key)
        model.base_url = dto.base_url.strip().rstrip("/")
        # 本地 HTML 抓取属于后续阶段，配置项仅作为路线图占位，不能进入可用搜索源。
        model.is_enabled = dto.is_enabled and not preset["is_local"]
        if preset["is_local"]:
            model.is_default = False
        model.params = {**{"maxResults": 5, "searchDepth": "basic"}, **dto.params}
        model.timeout_seconds = dto.timeout_seconds
        await self._db.flush()
        await self._db.refresh(model)
        return self._dto(model, provider_id)

    async def set_default(self, provider_id: str) -> SearchProviderDTO:
        preset = SEARCH_PROVIDER_PRESETS.get(provider_id)
        if not preset:
            raise NotFoundError("搜索服务商不存在")
        if preset["is_local"]:
            raise BusinessError("本地搜索源暂未启用，暂不能设为默认")
        model = await self._db.get(SearchProviderConfigModel, provider_id)
        if model is None or not model.is_enabled:
            raise BusinessError("请先启用并保存该搜索服务商")
        if model.provider_type != "searxng" and model.provider_type != "scrape" and not model.api_key:
            raise BusinessError("请先配置 API 密钥")
        await self._db.execute(update(SearchProviderConfigModel).values(is_default=False))
        model.is_default = True
        await self._db.flush()
        await self._db.refresh(model)
        return self._dto(model, provider_id)

    async def _search_with(self, model: SearchProviderConfigModel, query: str, max_results: int | None = None) -> list[WebSearchResult]:
        params = model.params or {}
        max_results = max_results or int(params.get("maxResults", 5))
        search_depth = str(params.get("searchDepth", "basic"))
        return await WebSearchService(
            provider_id=model.id,
            api_key=decrypt_value(model.api_key),
            base_url=model.base_url,
            timeout=model.timeout_seconds,
        ).search(
            query,
            max_results=max(1, min(max_results, 20)),
            search_depth=search_depth,
        )

    async def test_provider(self, provider_id: str) -> SearchProviderTestResponse:
        model = await self._db.get(SearchProviderConfigModel, provider_id)
        if model is None:
            raise NotFoundError("请先保存搜索服务商配置")
        try:
            results = await self._search_with(model, "test", 1)
        except Exception as exc:  # noqa: BLE001
            return SearchProviderTestResponse(success=False, message=str(exc))
        if not results:
            return SearchProviderTestResponse(success=False, message="服务可访问，但没有返回结果")
        return SearchProviderTestResponse(success=True, message="连接成功", result_count=len(results))

    async def availability(self) -> SearchProviderAvailabilityDTO:
        result = await self._db.execute(
            select(SearchProviderConfigModel).where(
                SearchProviderConfigModel.is_enabled.is_(True),
                SearchProviderConfigModel.is_default.is_(True),
            )
        )
        model = result.scalar_one_or_none()
        available = model is not None and model.provider_type != "scrape"
        return SearchProviderAvailabilityDTO(
            available=available,
            provider_name=model.name if available and model else "",
        )

    async def search_default(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(SearchProviderConfigModel).where(
                SearchProviderConfigModel.is_enabled.is_(True),
                SearchProviderConfigModel.is_default.is_(True),
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise BusinessError("未配置可用的联网搜索服务商")
        if model.provider_type == "scrape":
            raise BusinessError("本地搜索源暂未启用，请配置 API 搜索服务商")
        return [item.as_dict() for item in await self._search_with(model, query, max_results)]
