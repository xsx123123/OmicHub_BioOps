"""Agent Runtime 网关测试。"""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from cygnusx.application.services.chat.agent_runtime_gateway import AgentRuntimeGateway
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class _Gateway(AgentRuntimeGateway):
    async def _stream_agent_chat_inner(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatChunk]:
        del args, kwargs
        yield ChatChunk(type="error", content="legacy path should not run")


class _Span:
    def __enter__(self) -> "_Span":
        return self

    def __exit__(self, *args: Any) -> None:
        del args

    def record_exception(self, error: Exception) -> None:
        del error

    def set_attribute(self, key: str, value: Any) -> None:
        del key, value


class _Tracer:
    def start_as_current_span(self, *args: Any, **kwargs: Any) -> _Span:
        del args, kwargs
        return _Span()


class _Counter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


@pytest.mark.asyncio
async def test_gateway_routes_to_runtime_when_refactor_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _Router:
        def __init__(self, service: Any) -> None:
            captured["service"] = service

        async def stream(self, request: Any) -> AsyncIterator[ChatChunk]:
            captured["request"] = request
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.ChatRouterService", _Router
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=True),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )
    gateway = _Gateway()

    chunks = [
        chunk
        async for chunk in gateway.stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
        )
    ]

    assert [chunk.type for chunk in chunks] == ["done"]
    assert captured["service"] is gateway
    assert captured["request"].agent_id == "agent-1"


@pytest.mark.asyncio
async def test_gateway_records_legacy_entry_when_refactor_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _Counter()
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=False),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway._legacy_runtime_entry_count",
        counter,
    )

    chunks = [
        chunk
        async for chunk in _Gateway().stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            mode="studio",
        )
    ]

    assert [chunk.type for chunk in chunks] == ["error"]
    assert counter.calls == [(1, {"agent.id": "agent-1", "chat.mode": "studio"})]


@pytest.mark.asyncio
async def test_gateway_survives_cross_task_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """消费方每次 anext 换 Task（各自 copy Context）时网关也必须正常收尾。

    回归：旧实现 finally 中 agent_parent_context_var.reset(token) 与
    start_as_current_span 的 with 退出（OTel detach）跨 Context 会抛
    "Token was created in a different Context"。
    这里不打桩 get_tracer：未初始化遥测时返回的 noop tracer 仍会真实
    attach/detach context，正好覆盖 OTel 一侧的跨 Context 路径。
    """
    import asyncio

    class _Router:
        def __init__(self, service: Any) -> None:
            del service

        async def stream(self, request: Any) -> AsyncIterator[ChatChunk]:
            del request
            yield ChatChunk(type="text", content="a")
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.ChatRouterService", _Router
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=True),
    )

    gen = _Gateway().stream_agent_chat(
        user_id="user-1",
        agent_id="agent-1",
        messages=[{"role": "user", "content": "hello"}],
    )
    chunks: list[ChatChunk] = []
    while True:
        try:
            chunk = await asyncio.ensure_future(anext(gen))
        except StopAsyncIteration:
            break
        chunks.append(chunk)

    assert [chunk.type for chunk in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_gateway_threads_page_context_into_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """page_context 应合入 runtime_context，供 Runtime 注入系统提示词。"""
    captured: dict[str, Any] = {}

    class _Router:
        def __init__(self, service: Any) -> None:
            del service

        async def stream(self, request: Any) -> AsyncIterator[ChatChunk]:
            captured["request"] = request
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.ChatRouterService", _Router
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=True),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )

    chunks = [
        chunk
        async for chunk in _Gateway().stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            page_context="页面名称：首页；访问路径：/",
            runtime_context={"existing": 1},
        )
    ]

    assert [chunk.type for chunk in chunks] == ["done"]
    assert captured["request"].runtime_context == {
        "existing": 1,
        "page_context": "页面名称：首页；访问路径：/",
    }


@pytest.mark.asyncio
async def test_gateway_threads_page_context_into_legacy_inner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """关闭 runtime 重构时，page_context 经 legacy inner 的 runtime_context 透传。"""
    received: dict[str, Any] = {}

    class _LegacyGateway(AgentRuntimeGateway):
        async def _stream_agent_chat_inner(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatChunk]:
            received["kwargs"] = kwargs
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=False),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway._legacy_runtime_entry_count",
        _Counter(),
    )

    chunks = [
        chunk
        async for chunk in _LegacyGateway().stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            page_context="页面名称：任务中心；访问路径：/tasks",
        )
    ]

    assert [chunk.type for chunk in chunks] == ["done"]
    assert received["kwargs"]["runtime_context"]["page_context"] == "页面名称：任务中心；访问路径：/tasks"


@pytest.mark.asyncio
async def test_gateway_threads_auto_approve_into_runtime_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI 助手页面的 auto_approve 应随 ChatRuntimeRequest 下发，且缺省不置位。"""
    captured: dict[str, Any] = {}

    class _Router:
        def __init__(self, service: Any) -> None:
            del service

        async def stream(self, request: Any) -> AsyncIterator[ChatChunk]:
            captured["request"] = request
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.ChatRouterService", _Router
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=True),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )

    chunks = [
        chunk
        async for chunk in _Gateway().stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            auto_approve=True,
        )
    ]

    assert [chunk.type for chunk in chunks] == ["done"]
    assert captured["request"].auto_approve is True


@pytest.mark.asyncio
async def test_gateway_threads_auto_approve_into_legacy_inner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """关闭 runtime 重构时，auto_approve 经 legacy inner 透传。"""
    received: dict[str, Any] = {}

    class _LegacyGateway(AgentRuntimeGateway):
        async def _stream_agent_chat_inner(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatChunk]:
            received["kwargs"] = kwargs
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=False),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway.get_tracer",
        lambda name: _Tracer(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.agent_runtime_gateway._legacy_runtime_entry_count",
        _Counter(),
    )

    chunks = [
        chunk
        async for chunk in _LegacyGateway().stream_agent_chat(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            auto_approve=True,
        )
    ]

    assert [chunk.type for chunk in chunks] == ["done"]
    assert received["kwargs"]["auto_approve"] is True


def test_chat_stream_request_defaults_auto_approve_to_none() -> None:
    """未传 auto_approve（AI 工作台页面）时不得默认开启免审批。"""
    from cygnusx.application.schemas.chat import ChatStreamRequest

    request = ChatStreamRequest(
        messages=[{"role": "user", "content": "hello"}], stream=True
    )

    assert request.auto_approve is None
