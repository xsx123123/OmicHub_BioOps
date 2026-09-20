"""Agent 跨会话长期记忆的无数据库安全契约测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.agent_memory_service import AgentMemoryService
from cygnusx.application.services.agent_memory_tool_service import AgentMemoryToolService
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.agent_memory import (
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
        "cygnusx.application.services.agent_memory_service.get_settings", lambda: settings
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
        "cygnusx.application.services.agent_memory_service.get_settings", lambda: settings
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
        "cygnusx.application.services.agent_memory_service.get_settings", lambda: settings
    )

    class WrongDimensionEmbeddingClient:
        async def embeddings(self, _text: str, *, model: str) -> list[float]:
            assert model == "text-embedding-3-small"
            return [0.1, 0.2]

    service = AgentMemoryService(AsyncMock(), embedding_client=WrongDimensionEmbeddingClient())

    assert await service._embed("测试") == []


# --- M1：v2 共享分区召回两路合并 ---

def _v2_settings(**overrides) -> SimpleNamespace:
    base = {
        "memory_v2_enabled": True,
        "memory_fact_time_decay_lambda": 0.02,
        "agent_memory_embedding_model": "text-embedding-3-small",
        "agent_memory_semantic_retrieval_enabled": True,
        "agent_memory_semantic_candidate_limit": 100,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FixedEmbeddingClient:
    async def embeddings(self, _text: str, *, model: str) -> list[float]:
        return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]


def _fact(
    fact_id: int,
    agent_id: str,
    scope: str,
    content: str,
    *,
    similarity: float = 0.9,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=fact_id,
        user_id="user-1",
        agent_id=agent_id,
        scope=scope,
        content=content,
        keywords=[],
        embedding=None,
        embedding_model=None,
        source_session_id=None,
        source_message_ids=[],
        confidence=1.0,
        status="active",
        created_at=datetime.now(UTC),
        last_recalled_at=None,
        superseded_by=None,
        similarity=similarity,
    )


def _patch_fact_store(monkeypatch, partitions: dict[str, list]) -> list[str]:
    """按分区返回预置事实的 FakeStore；返回每次召回命中的分区序列。"""
    calls: list[str] = []

    class FakeStore:
        def __init__(self, _db) -> None:
            pass

        async def search(self, user_id, agent_id, query_vector, limit=10):
            calls.append(agent_id)
            return list(partitions.get(agent_id, []))[:limit]

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.PostgresFactStore", FakeStore
    )
    return calls


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


def _block(block_id: int, agent_id: str, name: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=block_id, agent_id=agent_id, block_name=name, content=content, char_limit=2000
    )


@pytest.mark.asyncio
async def test_v2_search_merges_shared_partition_across_agents(monkeypatch) -> None:
    """agent A 写入共享偏好（agent_id=""），agent B 召回可见，且共享层结果优先。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(),
    )
    shared_pref = _fact(1, "", "preference", "结果图都用英文标注")
    b_project = _fact(2, "agent-b", "project", "agent-b 的项目事实")
    calls = _patch_fact_store(monkeypatch, {"": [shared_pref], "agent-b": [b_project]})

    service = AgentMemoryService(AsyncMock(), embedding_client=_FixedEmbeddingClient())
    result = await service.search_memory(user_id="user-1", query="绘图偏好", agent_id="agent-b")

    assert [m["content"] for m in result["memories"]] == [
        "结果图都用英文标注",
        "agent-b 的项目事实",
    ]
    assert calls == ["", "agent-b"]


@pytest.mark.asyncio
async def test_v2_search_keeps_agent_partition_isolated(monkeypatch) -> None:
    """agent 分区事实（project/summary）不被其他 agent 召回。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(),
    )
    a_project = _fact(3, "agent-a", "project", "agent-a 的项目事实")
    calls = _patch_fact_store(monkeypatch, {"agent-a": [a_project]})

    service = AgentMemoryService(AsyncMock(), embedding_client=_FixedEmbeddingClient())
    result = await service.search_memory(user_id="user-1", query="项目", agent_id="agent-b")

    assert result["memories"] == []
    assert "agent-a" not in calls


@pytest.mark.asyncio
async def test_v2_search_dedupes_when_current_agent_is_shared_partition(monkeypatch) -> None:
    """当前 agent 即共享分区时两路命中同一事实，去重后不重复返回。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(),
    )
    shared_pref = _fact(1, "", "preference", "结果图都用英文标注")
    calls = _patch_fact_store(monkeypatch, {"": [shared_pref]})

    service = AgentMemoryService(AsyncMock(), embedding_client=_FixedEmbeddingClient())
    result = await service.search_memory(user_id="user-1", query="绘图偏好", agent_id=None)

    assert [m["id"] for m in result["memories"]] == ["1"]
    assert calls == [""]


@pytest.mark.asyncio
async def test_v2_prompt_context_merges_shared_blocks_and_facts(monkeypatch) -> None:
    """build_prompt_context_v2：共享层块 + 当前 agent 块、共享事实 + 分区事实均注入。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(),
    )
    blocks = [
        _block(1, "", "profile", "用户画像：肿瘤方向 PI"),
        _block(2, "agentteams-manager", "current_focus", "当前关注：协作室交付"),
    ]
    shared_pref = _fact(1, "", "preference", "结果图都用英文标注")
    mgr_fact = _fact(2, "agentteams-manager", "summary", "manager 分区摘要")
    _patch_fact_store(monkeypatch, {"": [shared_pref], "agentteams-manager": [mgr_fact]})

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_FakeScalars(blocks))
    service = AgentMemoryService(db, embedding_client=_FixedEmbeddingClient())

    content = await service.build_prompt_context_v2("user-1", "agentteams-manager", "画图")

    assert content.startswith("<user_memory>")
    assert content.rstrip().endswith("</user_memory>")
    assert "用户画像：肿瘤方向 PI" in content
    assert "当前关注：协作室交付" in content
    assert "结果图都用英文标注" in content
    assert "manager 分区摘要" in content
    # 共享层块排前
    assert content.index("用户画像") < content.index("当前关注")


@pytest.mark.asyncio
async def test_v2_prompt_context_enforces_3200_byte_budget(monkeypatch) -> None:
    """注入预算截断生效：超长块被截到 3200 字节以内且包装完整。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(),
    )
    blocks = [_block(1, "", "profile", "长" * 5000)]
    _patch_fact_store(monkeypatch, {})

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_FakeScalars(blocks))
    service = AgentMemoryService(db, embedding_client=_FixedEmbeddingClient())

    content = await service.build_prompt_context_v2("user-1", "agent-b", "任意问题")

    assert len(content.encode("utf-8")) <= 3200
    assert content.startswith("<user_memory>")


@pytest.mark.asyncio
async def test_v2_off_search_does_not_touch_fact_store(monkeypatch) -> None:
    """v2 off 回归：旧 agent_memories 链路不变，完全不经过 v2 FactStore。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: _v2_settings(
            memory_v2_enabled=False,
            agent_memory_semantic_retrieval_enabled=False,
            agent_memory_embedding_model="",
        ),
    )

    class _ForbiddenStore:
        def __init__(self, _db) -> None:
            raise AssertionError("v2 off 不应触达 FactStore")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.PostgresFactStore", _ForbiddenStore
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_FakeScalars([]))
    service = AgentMemoryService(db, embedding_client=_FixedEmbeddingClient())

    result = await service.search_memory(user_id="user-1", query="偏好", agent_id="agent-b")

    assert result == {"memories": [], "count": 0}
