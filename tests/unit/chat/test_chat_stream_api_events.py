"""聊天 SSE API 出口的事件校验覆盖。"""

import asyncio
import contextvars
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cygnusx.api.v1 import chat as chat_api
from cygnusx.application.schemas.chat import ChatStreamRequest
from cygnusx.application.services.chat.chat_event_service import ChatEventService
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class _Db:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _EventService:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def before_send(self, chunk: ChatChunk) -> ChatChunk:
        self.seen.append(chunk.type)
        return chunk

    def after_stream(self) -> None:
        return None


@pytest.mark.asyncio
async def test_sse_exit_validates_legacy_path_when_refactor_is_disabled(monkeypatch) -> None:
    event_service = _EventService()

    class _ChatService:
        def __init__(self, _db) -> None:
            pass

        async def stream_chat(self, **_kwargs):
            yield ChatChunk(type="text", content="answer")
            yield ChatChunk(type="done")

    monkeypatch.setattr(chat_api, "ChatService", _ChatService)
    monkeypatch.setattr(
        chat_api.ChatEventService,
        "from_settings",
        classmethod(lambda cls: event_service),
    )
    monkeypatch.setattr(
        chat_api,
        "get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=False),
    )
    db = _Db()
    request = ChatStreamRequest(
        messages=[{"role": "user", "content": "hello"}],
        model_id=uuid4(),
    )

    response = await chat_api.chat_stream(request, "user-1", db)
    payload = "".join([chunk async for chunk in response.body_iterator])

    assert event_service.seen == ["text", "done"]
    assert '"type": "done"' in payload
    assert db.committed


@pytest.mark.asyncio
async def test_sse_exit_reports_incomplete_execution_lifecycle(monkeypatch) -> None:
    class _ChatService:
        def __init__(self, _db) -> None:
            pass

        async def stream_chat(self, **_kwargs):
            yield ChatChunk(type="agent_turn_started")
            yield ChatChunk(type="agent_final_result")

    monkeypatch.setattr(chat_api, "ChatService", _ChatService)
    monkeypatch.setattr(
        chat_api,
        "get_settings",
        lambda: SimpleNamespace(chat_runtime_refactor_enabled=False, app_env="test"),
    )
    monkeypatch.setattr(
        chat_api.ChatEventService,
        "from_settings",
        classmethod(lambda cls: ChatEventService(enforcement="raise")),
    )
    request = ChatStreamRequest(
        messages=[{"role": "user", "content": "hello"}],
        model_id=uuid4(),
    )
    response = await chat_api.chat_stream(request, "user-1", _Db())

    payload = "".join([chunk async for chunk in response.body_iterator])

    assert '"type": "error"' in payload
    assert '"error_code": "chat_stream_failed"' in payload
    assert "执行生命周期必须以 done 事件收尾" in payload


def test_event_service_uses_configured_enforcement_without_environment_override(monkeypatch) -> None:
    settings = SimpleNamespace(
        app_env="development",
        chat_event_sequence_enforcement="warn",
    )

    service = ChatEventService.from_settings(settings)

    assert service.enforcement == "warn"


@pytest.mark.asyncio
async def test_sse_exit_accepts_runtime_failure_terminal_sequence(monkeypatch) -> None:
    class _ChatService:
        def __init__(self, _db) -> None:
            pass

        async def stream_agent_chat(self, **_kwargs):
            yield ChatChunk(type="agent_turn_started")
            yield ChatChunk(type="error", content="provider unavailable")
            yield ChatChunk(type="agent_turn_failed")
            yield ChatChunk(type="done")

    monkeypatch.setattr(chat_api, "ChatService", _ChatService)
    monkeypatch.setattr(
        chat_api.ChatEventService,
        "from_settings",
        classmethod(lambda cls: ChatEventService(enforcement="raise")),
    )
    request = ChatStreamRequest(
        agent_id="agent-1",
        messages=[{"role": "user", "content": "hello"}],
        model_id=uuid4(),
    )
    db = _Db()

    response = await chat_api.chat_stream(request, "user-1", db)
    payload = "".join([chunk async for chunk in response.body_iterator])

    assert '"type": "agent_turn_failed"' in payload
    assert '"type": "done"' in payload
    assert db.committed


@pytest.mark.asyncio
async def test_with_sse_heartbeat_emits_heartbeat_during_silence() -> None:
    async def slow_stream():
        await asyncio.sleep(0.05)
        yield ChatChunk(type="text", content="answer")
        yield ChatChunk(type="done")

    chunks = [
        chunk
        async for chunk in chat_api._with_sse_heartbeat(slow_stream(), interval=0.01)
    ]

    assert chunks[0].type == "heartbeat"
    assert [c.type for c in chunks][-2:] == ["text", "done"]


@pytest.mark.asyncio
async def test_with_sse_heartbeat_passthrough_when_stream_is_active() -> None:
    async def fast_stream():
        yield ChatChunk(type="text", content="answer")
        yield ChatChunk(type="done")

    chunks = [
        chunk
        async for chunk in chat_api._with_sse_heartbeat(fast_stream(), interval=60.0)
    ]

    assert [c.type for c in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_with_sse_heartbeat_close_cancels_pending_wait() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hung_stream():
        started.set()
        try:
            await asyncio.sleep(3600)
            yield ChatChunk(type="text", content="never")
        except asyncio.CancelledError:
            cancelled.set()
            raise

    wrapper = chat_api._with_sse_heartbeat(hung_stream(), interval=0.01)
    task = asyncio.ensure_future(anext(aiter(wrapper)))
    await started.wait()
    first = await task  # 上游静默超时 → 先拿到心跳，此时 pending 仍挂在 hung_stream 上
    assert first.type == "heartbeat"
    await wrapper.aclose()

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_with_sse_heartbeat_runs_stream_in_single_context() -> None:
    """上游生成器的 ContextVar set/reset 必须在同一个 Context 中执行。

    回归：旧实现把每次 anext 包成独立 Task（各自 copy Context），生成器收尾时
    reset(token) 跨 Context 抛 "Token was created in a different Context"
    （cygnusx_agent_parent_context 报错来源）。
    """
    var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "test_sse_heartbeat_ctx", default=None
    )

    async def ctx_stream():
        token = var.set("x")
        try:
            await asyncio.sleep(0.05)  # 跨越多个心跳窗口，旧实现会切换 Task
            yield ChatChunk(type="text", content="answer")
            await asyncio.sleep(0.02)
            yield ChatChunk(type="done")
        finally:
            var.reset(token)

    chunks = [
        chunk
        async for chunk in chat_api._with_sse_heartbeat(ctx_stream(), interval=0.01)
    ]

    assert [c.type for c in chunks if c.type != "heartbeat"] == ["text", "done"]


@pytest.mark.asyncio
async def test_with_sse_heartbeat_propagates_upstream_error() -> None:
    async def failing_stream():
        yield ChatChunk(type="text", content="partial")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        async for _ in chat_api._with_sse_heartbeat(failing_stream(), interval=60.0):
            pass
