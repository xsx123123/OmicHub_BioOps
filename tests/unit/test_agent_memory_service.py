"""Agent 跨会话长期记忆的无数据库安全契约测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.application.services.agent_memory_service import AgentMemoryService
from omichub.application.services.agent_memory_tool_service import AgentMemoryToolService
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.agent_memory import (
    EMBEDDING_DIMENSIONS,
    AgentMemoryModel,
)


def test_memory_content_rejects_sensitive_credentials() -> None:
    with pytest.raises(BusinessError, match="敏感凭据"):
        AgentMemoryService._validate_content("我的 API_KEY 是 sk-super-secret-token-value")


def test_memory_content_and_scope_limits_are_enforced() -> None:
    assert AgentMemoryService._validate_content("用户常用小鼠脑 10x V3 数据") == "用户常用小鼠脑 10x V3 数据"
    assert AgentMemoryService._validate_scope("project") == "project"

    with pytest.raises(BusinessError, match="不能超过"):
        AgentMemoryService._validate_content("a" * 201)
    with pytest.raises(BusinessError, match="不支持的记忆范围"):
        AgentMemoryService._validate_scope("temporary")


def test_memory_keywords_are_bounded_and_deduplicated() -> None:
    keywords = AgentMemoryService._normalize_keywords(
        ["Mouse", "mouse", "10x", "GRCh38", "RNA", "single-cell", "project", "brain", "extra"],
        "ignored",
    )

    assert keywords == ["mouse", "10x", "grch38", "rna", "single-cell", "project", "brain", "extra"]


def test_profile_memory_is_shared_but_project_memory_is_agent_scoped() -> None:
    context = type("Context", (), {"agent_id": "agent-scrna"})()

    assert AgentMemoryToolService._memory_agent_id("profile", context) is None
    assert AgentMemoryToolService._memory_agent_id("preference", context) is None
    assert AgentMemoryToolService._memory_agent_id("project", context) == "agent-scrna"


def test_conflict_adjudication_parser_accepts_only_supported_actions() -> None:
    assert AgentMemoryService._parse_conflict_action(
        {"choices": [{"message": {"content": '{"action":"coexist"}'}}]}
    ) == "coexist"
    assert AgentMemoryService._parse_conflict_action(
        {"choices": [{"message": {"content": '{"action":"unsafe"}'}}]}
    ) == "update"


@pytest.mark.asyncio
async def test_semantic_rank_prefers_embedding_similarity(monkeypatch) -> None:
    settings = SimpleNamespace(
        agent_memory_semantic_retrieval_enabled=True,
        agent_memory_embedding_model="text-embedding-3-small",
        agent_memory_semantic_candidate_limit=100,
    )
    monkeypatch.setattr(
        "omichub.application.services.agent_memory_service.get_settings", lambda: settings
    )

    class EmbeddingClient:
        async def embeddings(self, _text: str, *, model: str) -> list[float]:
            assert model == "text-embedding-3-small"
            return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]

    now = datetime.now(UTC)
    lexical_only = AgentMemoryModel(
        content="小鼠脑单细胞项目",
        keywords=["小鼠"],
        embedding=[0.0, 1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 2))],
        updated_at=now,
    )
    semantic_match = AgentMemoryModel(
        content="肿瘤转录组分析偏好",
        keywords=[],
        embedding=[1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))],
        updated_at=now,
    )
    service = AgentMemoryService(AsyncMock(), embedding_client=EmbeddingClient())

    ranked = await service._semantic_rank(
        [lexical_only, semantic_match], "请继续这个转录组项目", ["项目"], 2
    )

    assert ranked == [semantic_match, lexical_only]


@pytest.mark.asyncio
async def test_embedding_failure_returns_empty_vector_for_keyword_fallback(monkeypatch) -> None:
    settings = SimpleNamespace(
        agent_memory_semantic_retrieval_enabled=True,
        agent_memory_embedding_model="text-embedding-3-small",
        agent_memory_semantic_candidate_limit=100,
    )
    monkeypatch.setattr(
        "omichub.application.services.agent_memory_service.get_settings", lambda: settings
    )

    class BrokenEmbeddingClient:
        async def embeddings(self, _text: str, *, model: str) -> list[float]:
            raise RuntimeError("embedding service unavailable")

    service = AgentMemoryService(AsyncMock(), embedding_client=BrokenEmbeddingClient())

    assert await service._embed("测试") == []


@pytest.mark.asyncio
async def test_wrong_dimension_embedding_returns_empty_vector_for_keyword_fallback(monkeypatch) -> None:
    settings = SimpleNamespace(
        agent_memory_semantic_retrieval_enabled=True,
        agent_memory_embedding_model="text-embedding-3-small",
        agent_memory_semantic_candidate_limit=100,
    )
    monkeypatch.setattr(
        "omichub.application.services.agent_memory_service.get_settings", lambda: settings
    )

    class WrongDimensionEmbeddingClient:
        async def embeddings(self, _text: str, *, model: str) -> list[float]:
            assert model == "text-embedding-3-small"
            return [0.1, 0.2]

    service = AgentMemoryService(AsyncMock(), embedding_client=WrongDimensionEmbeddingClient())

    assert await service._embed("测试") == []
