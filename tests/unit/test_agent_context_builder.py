"""AgentContextBuilder 的缓存与一次性上下文构建测试。"""

from types import SimpleNamespace
import time

import pytest

from cygnusx.application.services.agent_context_builder import AgentContextBuilder


class _AgentService:
    def __init__(self) -> None:
        self.calls = 0

    async def assemble_context(
        self, agent_id: str, *, user_id: str | None = None, tool_query: str | None = None
    ) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            agent=SimpleNamespace(agent_id=agent_id),
            model_config=None,
            system_prompt=f"{user_id}:{tool_query}",
            tools=[{"function": {"name": "base_tool"}}],
            mcp_servers=[],
            skills=[],
            features={"runtime": {"web_search": True}},
        )


@pytest.mark.asyncio
async def test_builder_caches_by_agent_user_mode_and_message() -> None:
    AgentContextBuilder._cache.clear()
    agent_service = _AgentService()
    builder = AgentContextBuilder(SimpleNamespace(), agent_service)  # type: ignore[arg-type]
    session = SimpleNamespace(session_id="session-1", user_id="user-1")

    first = await builder.build_for_session(session, "agent-1", user_message="hello", mode="chat")
    second = await builder.build_for_session(session, "agent-1", user_message="hello", mode="chat")

    assert first is not None
    assert second is not None
    assert first.session_id == "session-1"
    assert first.agent.agent_id == "agent-1"
    assert first.run_id != second.run_id
    assert agent_service.calls == 1


@pytest.mark.asyncio
async def test_builder_assemble_returns_cached_mutable_runtime_context() -> None:
    AgentContextBuilder._cache.clear()
    agent_service = _AgentService()
    builder = AgentContextBuilder(SimpleNamespace(), agent_service)  # type: ignore[arg-type]

    first = await builder.assemble("agent-1", "user-1", user_message="hello")
    assert first is not None
    first.model_config = "request-specific-override"
    second = await builder.assemble("agent-1", "user-1", user_message="hello")

    assert second is not None
    assert second.model_config is None
    assert agent_service.calls == 1


@pytest.mark.asyncio
async def test_builder_cache_isolates_nested_runtime_configuration() -> None:
    AgentContextBuilder._cache.clear()
    agent_service = _AgentService()
    builder = AgentContextBuilder(SimpleNamespace(), agent_service)  # type: ignore[arg-type]

    first = await builder.assemble("agent-1", "user-1", user_message="hello")
    assert first is not None
    first.tools[0]["function"]["name"] = "request_specific_tool"
    first.features["runtime"]["web_search"] = False

    second = await builder.assemble("agent-1", "user-1", user_message="hello")

    assert second is not None
    assert second.tools[0]["function"]["name"] == "base_tool"
    assert second.features["runtime"]["web_search"] is True
    assert agent_service.calls == 1


@pytest.mark.asyncio
async def test_builder_reassembles_after_cache_ttl_expiry() -> None:
    AgentContextBuilder._cache.clear()
    agent_service = _AgentService()
    builder = AgentContextBuilder(SimpleNamespace(), agent_service)  # type: ignore[arg-type]
    cache_key = builder._cache_key("agent-1", "user-1", "chat", "hello")

    assert await builder.assemble("agent-1", "user-1", user_message="hello") is not None
    AgentContextBuilder._cache[cache_key].expires_at = time.monotonic() - 1

    assert await builder.assemble("agent-1", "user-1", user_message="hello") is not None
    assert agent_service.calls == 2
