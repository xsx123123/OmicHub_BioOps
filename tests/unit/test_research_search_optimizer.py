from __future__ import annotations

import uuid

import pytest

from cygnusx.application.services.research_search_optimizer import ResearchSearchOptimizer


@pytest.mark.asyncio
async def test_refined_queries_are_reused_from_local_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenRedis:
        async def get(self, _key: str) -> None:
            raise RuntimeError("redis unavailable")

        async def setex(self, *_args: object) -> None:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "cygnusx.application.services.research_search_optimizer.get_redis",
        lambda: BrokenRedis(),
    )
    optimizer = ResearchSearchOptimizer(cache_ttl_seconds=300)
    query = f"TP53 lung cancer immune tolerance {uuid.uuid4()}"
    calls = 0

    async def refiner(_query: str) -> dict[str, list[str]]:
        nonlocal calls
        calls += 1
        return {"queries": ["TP53 AND lung cancer", "macrophage AND immune tolerance"]}

    first = await optimizer.refine_queries(
        query,
        fallback_queries=[query],
        refiner=refiner,
    )
    second = await optimizer.refine_queries(
        query,
        fallback_queries=[query],
        refiner=refiner,
    )

    assert first["status"] == "refined"
    assert second["status"] == "cached"
    assert second["cache_hit"] is True
    assert calls == 1


@pytest.mark.asyncio
async def test_rerank_prefers_title_and_abstract_matching_the_question() -> None:
    optimizer = ResearchSearchOptimizer()
    results = await optimizer.rerank(
        "TP53 lung cancer macrophage immune tolerance",
        [
            {
                "title": "General lung cancer epidemiology",
                "snippet": "Population incidence and smoking exposure.",
                "url": "https://example.org/epidemiology",
            },
            {
                "title": "TP53 shapes macrophage-mediated immune tolerance in lung cancer",
                "abstract": "Tumor-associated macrophages suppress T cell activity.",
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "provider": "europe_pmc",
            },
        ],
        limit=5,
    )

    assert results[0]["provider"] == "europe_pmc"
    assert results[0]["quality"]["rerank_method"] in {
        "embedding_hybrid",
        "lexical_hybrid",
    }
