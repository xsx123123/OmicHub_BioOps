"""Shared query refinement cache and semantic search-result reranking."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from omichub.core.config import get_settings
from omichub.infrastructure.cache.redis_client import get_redis

QueryRefiner = Callable[[str], Awaitable[Any]]

_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{1,}|[\u4e00-\u9fff]{2,}")
_CACHE_PREFIX = "research-search:refined:v1:"
_LOCAL_CACHE: dict[str, tuple[float, list[str]]] = {}
_REDIS_DISABLED_UNTIL = 0.0


class ResearchSearchOptimizer:
    """Optimize search quality without making Redis or embeddings mandatory."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: int | None = None,
        embedding_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        configured_ttl = getattr(settings, "web_search_refinement_cache_ttl_seconds", 86400)
        self._cache_ttl = max(60, int(cache_ttl_seconds or configured_ttl))
        self._embedding_client = embedding_client

    async def refine_queries(
        self,
        query: str,
        *,
        fallback_queries: Sequence[str],
        refiner: QueryRefiner | None = None,
    ) -> dict[str, Any]:
        fallback = self._normalize_queries(fallback_queries)
        cached = await self._cache_get(query)
        if cached:
            return {"status": "cached", "queries": cached, "cache_hit": True}
        if refiner is None:
            return {"status": "fallback", "queries": fallback, "cache_hit": False}

        started = time.monotonic()
        try:
            raw = await refiner(query)
            value = raw.get("queries") if isinstance(raw, Mapping) else raw
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise ValueError("query refiner did not return a query list")
            queries = self._normalize_queries(value)
            if not 2 <= len(queries) <= 4:
                raise ValueError("query refiner must return 2-4 queries")
            await self._cache_set(query, queries)
            return {
                "status": "refined",
                "queries": queries,
                "cache_hit": False,
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            }
        except Exception as exc:  # noqa: BLE001 - fallback keeps search available
            return {
                "status": "fallback",
                "queries": fallback,
                "cache_hit": False,
                "error": self._safe_error(exc),
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            }

    async def rerank(
        self,
        query: str,
        items: Sequence[Mapping[str, Any]],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        candidates = self._deduplicate(items)
        if not candidates:
            return []

        query_tokens = self._tokens(query)
        lexical_scores = [self._lexical_score(query_tokens, item) for item in candidates]
        semantic_scores = await self._embedding_scores(query, candidates)
        ranked: list[tuple[float, int, dict[str, Any]]] = []
        for index, item in enumerate(candidates):
            existing = float((item.get("quality") or {}).get("relevance_score") or 0)
            authority = self._authority_score(item)
            semantic = semantic_scores[index] if semantic_scores else lexical_scores[index]
            score = semantic * 0.58 + lexical_scores[index] * 0.27 + authority * 0.1
            score += min(existing / 10.0, 1.0) * 0.05
            enriched = dict(item)
            quality = dict(enriched.get("quality") or {})
            quality.update(
                {
                    "rerank_score": round(score, 6),
                    "semantic_score": round(semantic, 6),
                    "lexical_score": round(lexical_scores[index], 6),
                    "rerank_method": "embedding_hybrid" if semantic_scores else "lexical_hybrid",
                }
            )
            enriched["quality"] = quality
            ranked.append((score, -index, enriched))
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [item for _, _, item in ranked[: max(1, min(int(limit), 20))]]

    async def _embedding_scores(
        self,
        query: str,
        items: Sequence[Mapping[str, Any]],
    ) -> list[float]:
        settings = get_settings()
        enabled = bool(getattr(settings, "web_search_semantic_rerank_enabled", True))
        model = str(
            getattr(settings, "web_search_embedding_model", "")
            or settings.agent_memory_embedding_model
        ).strip()
        if not enabled or not model:
            return []
        try:
            if self._embedding_client is None:
                from omichub.infrastructure.ai_provider.litellm_provider import LiteLLMProvider

                self._embedding_client = LiteLLMProvider()
            documents = [self._document_text(item)[:2400] for item in items]
            vectors = await asyncio.gather(
                self._embedding_client.embeddings(query[:1200], model=model),
                *(self._embedding_client.embeddings(text, model=model) for text in documents),
            )
            query_vector = [float(value) for value in vectors[0]]
            if not query_vector:
                return []
            return [self._cosine(query_vector, [float(value) for value in vector]) for vector in vectors[1:]]
        except Exception as exc:  # noqa: BLE001 - lexical rerank is the availability fallback
            logger.warning("搜索结果语义重排失败，回退词项重排: {}", exc)
            return []

    async def _cache_get(self, query: str) -> list[str]:
        global _REDIS_DISABLED_UNTIL
        key = self._cache_key(query)
        local = _LOCAL_CACHE.get(key)
        if local and local[0] > time.monotonic():
            return list(local[1])
        _LOCAL_CACHE.pop(key, None)
        if time.monotonic() < _REDIS_DISABLED_UNTIL:
            return []
        try:
            raw = await asyncio.wait_for(
                get_redis().get(f"{_CACHE_PREFIX}{key}"),
                timeout=0.25,
            )
            parsed = json.loads(raw) if raw else []
            queries = self._normalize_queries(parsed)
            if 2 <= len(queries) <= 4:
                _LOCAL_CACHE[key] = (time.monotonic() + self._cache_ttl, queries)
                return queries
        except Exception as exc:  # noqa: BLE001 - Redis is optional for this optimization
            _REDIS_DISABLED_UNTIL = time.monotonic() + 30
            logger.debug("检索词缓存读取失败，使用进程内缓存: {}", exc)
        return []

    async def _cache_set(self, query: str, queries: Sequence[str]) -> None:
        global _REDIS_DISABLED_UNTIL
        key = self._cache_key(query)
        normalized = self._normalize_queries(queries)
        _LOCAL_CACHE[key] = (time.monotonic() + self._cache_ttl, normalized)
        if time.monotonic() < _REDIS_DISABLED_UNTIL:
            return
        try:
            await asyncio.wait_for(
                get_redis().setex(
                    f"{_CACHE_PREFIX}{key}",
                    self._cache_ttl,
                    json.dumps(normalized, ensure_ascii=False),
                ),
                timeout=0.25,
            )
        except Exception as exc:  # noqa: BLE001 - local cache still prevents repeated calls
            _REDIS_DISABLED_UNTIL = time.monotonic() + 30
            logger.debug("检索词缓存写入失败，保留进程内缓存: {}", exc)

    @staticmethod
    def _normalize_queries(values: Sequence[Any]) -> list[str]:
        queries: list[str] = []
        for value in values:
            normalized = " ".join(str(value or "").split())[:240]
            if normalized and normalized not in queries:
                queries.append(normalized)
        return queries[:4]

    @staticmethod
    def _cache_key(query: str) -> str:
        normalized = " ".join(query.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.casefold() for token in _TOKEN_PATTERN.findall(text)}

    @classmethod
    def _document_text(cls, item: Mapping[str, Any]) -> str:
        return " ".join(
            str(item.get(key) or "")
            for key in ("title", "name", "abstract", "snippet", "claim", "content", "text")
        ).strip()

    @classmethod
    def _lexical_score(cls, query_tokens: set[str], item: Mapping[str, Any]) -> float:
        if not query_tokens:
            return 0.0
        title_tokens = cls._tokens(str(item.get("title") or item.get("name") or ""))
        body_tokens = cls._tokens(cls._document_text(item))
        title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
        body_overlap = len(query_tokens & body_tokens) / len(query_tokens)
        return min(1.0, title_overlap * 0.65 + body_overlap * 0.35)

    @staticmethod
    def _authority_score(item: Mapping[str, Any]) -> float:
        provider = str(item.get("provider") or "").casefold()
        if provider in {"europe_pmc", "pubmed", "crossref"}:
            return 1.0
        host = urlparse(str(item.get("url") or item.get("link") or "")).netloc.casefold()
        return 1.0 if host.endswith((".gov", ".edu", ".ac.uk")) else 0.35

    @staticmethod
    def _deduplicate(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in items:
            item = dict(raw)
            key = (
                str(item.get("url") or item.get("link") or "").casefold().rstrip("/"),
                re.sub(r"\W+", "", str(item.get("title") or item.get("name") or "").casefold())[:160],
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = re.sub(
            r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            str(exc),
        )
        return (message or type(exc).__name__)[:500]
