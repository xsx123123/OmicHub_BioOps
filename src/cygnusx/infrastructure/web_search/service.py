"""统一的联网搜索适配层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from cygnusx.core.exceptions import BusinessError


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "publishedAt": self.published_at,
        }


class WebSearchService:
    """将多个搜索服务商的响应归一化为 WebSearchResult。"""

    def __init__(self, *, provider_id: str, api_key: str, base_url: str, timeout: int = 10) -> None:
        self.provider_id = provider_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = min(max(timeout, 1), 10)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> list[WebSearchResult]:
        if not query.strip():
            return []
        if self.provider_id in {"google", "bing", "baidu"}:
            raise BusinessError("本地免费搜索源暂未启用，请配置 API 搜索服务商")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            if self.provider_id == "tavily":
                response = await client.post(
                    f"{self.base_url}/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "advanced" if search_depth == "advanced" else "basic",
                    },
                )
                response.raise_for_status()
                return self._tavily(response.json())
            if self.provider_id == "exa":
                response = await client.post(
                    f"{self.base_url}/search",
                    headers={"x-api-key": self.api_key},
                    json={"query": query, "num_results": max_results, "contents": {"highlights": {"max_characters": 300}}},
                )
                response.raise_for_status()
                return self._exa(response.json())
            if self.provider_id == "bocha":
                response = await client.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"query": query, "count": max_results, "summary": True},
                )
                response.raise_for_status()
                return self._bocha(response.json())
            if self.provider_id == "zhipu":
                response = await client.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._zhipu_request_payload(query, max_results, search_depth),
                )
                response.raise_for_status()
                return self._zhipu(response.json())
            if self.provider_id == "searxng":
                response = await client.get(
                    f"{self.base_url}/search", params={"q": query, "format": "json", "language": "zh-CN"}
                )
                response.raise_for_status()
                return self._searxng(response.json(), max_results)
        raise BusinessError(f"不支持的搜索服务商: {self.provider_id}")

    @staticmethod
    def _item(item: dict[str, Any]) -> WebSearchResult | None:
        url = str(item.get("url") or item.get("link") or "")
        title = str(item.get("title") or item.get("name") or "")
        if not url or not title:
            return None
        snippet = str(item.get("content") or item.get("snippet") or item.get("description") or item.get("text") or "")[:300]
        published = (
            item.get("publish_date")
            or item.get("published_date")
            or item.get("publishedAt")
            or item.get("date")
        )
        return WebSearchResult(title=title, url=url, snippet=snippet, published_at=str(published) if published else None)

    @classmethod
    def _items(cls, items: list[dict[str, Any]], limit: int = 20) -> list[WebSearchResult]:
        return [result for item in items[:limit] if (result := cls._item(item))]

    @classmethod
    def _tavily(cls, data: dict[str, Any]) -> list[WebSearchResult]:
        return cls._items(data.get("results") or [])

    @classmethod
    def _exa(cls, data: dict[str, Any]) -> list[WebSearchResult]:
        results = []
        for item in data.get("results") or []:
            highlights = item.get("highlights") or []
            if highlights:
                item = {**item, "snippet": " ".join(map(str, highlights))}
            results.append(item)
        return cls._items(results)

    @classmethod
    def _bocha(cls, data: dict[str, Any]) -> list[WebSearchResult]:
        payload = data.get("data") or data
        pages = payload.get("webPages") or payload.get("web_pages") or []
        return cls._items(pages.get("value", []) if isinstance(pages, dict) else pages)

    @classmethod
    def _zhipu(cls, data: dict[str, Any]) -> list[WebSearchResult]:
        return cls._items(data.get("search_result") or data.get("results") or [])

    @staticmethod
    def _zhipu_request_payload(
        query: str,
        max_results: int,
        search_depth: str,
    ) -> dict[str, Any]:
        return {
            "search_query": query,
            "search_engine": "search_pro" if search_depth == "advanced" else "search_std",
            "search_intent": False,
            "count": max_results,
            "search_recency_filter": "noLimit",
            "content_size": "medium",
        }

    @classmethod
    def _searxng(cls, data: dict[str, Any], limit: int) -> list[WebSearchResult]:
        return cls._items(data.get("results") or [], limit)
