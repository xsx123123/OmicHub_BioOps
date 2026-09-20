"""直连聊天 Runtime 的统一入口测试。"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest
from cygnusx.application.services.chat.runtimes.direct_chat_runtime import DirectChatRuntime
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class _Service:
    pass


class _PersistenceService:
    def __init__(self) -> None:
        self.update_message_content = AsyncMock()
        self._commit_stream_anchor = AsyncMock()


@pytest.mark.asyncio
async def test_direct_runtime_requires_model_id() -> None:
    runtime = DirectChatRuntime(_Service())  # type: ignore[arg-type]
    request = ChatRuntimeRequest(user_id="user-1", agent_id="direct-chat", messages=[])

    chunks = [chunk async for chunk in runtime.run(request)]

    assert [(chunk.type, chunk.content) for chunk in chunks] == [
        ("error", "直连模型聊天缺少模型配置")
    ]


@pytest.mark.asyncio
async def test_direct_runtime_maps_request_to_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = DirectChatRuntime(_Service())  # type: ignore[arg-type]
    received: dict[str, Any] = {}

    async def fake_stream(*args: Any, **kwargs: Any) -> AsyncIterator[ChatChunk]:
        received["args"] = args
        received["kwargs"] = kwargs
        yield ChatChunk(type="done")

    monkeypatch.setattr(runtime, "stream", fake_stream)
    model_id = uuid4()
    request = ChatRuntimeRequest(
        user_id="user-1",
        agent_id="direct-chat",
        messages=[{"role": "user", "content": "hello"}],
        model_id=model_id,
        session_id="session-1",
        enable_web_search=True,
        project_id="project-1",
        runtime_context={
            "assistant_id": "assistant-1",
            "system_prompt": "system",
            "temperature": 0.2,
            "max_tokens": 128,
        },
    )

    assert [chunk.type async for chunk in runtime.run(request)] == ["done"]
    assert received["args"] == ("user-1", request.messages, model_id)
    assert received["kwargs"] == {
        "session_id": "session-1",
        "assistant_id": "assistant-1",
        "system_prompt": "system",
        "temperature": 0.2,
        "max_tokens": 128,
        "enable_web_search": True,
        "project_id": "project-1",
        "page_context": None,
    }


@pytest.mark.asyncio
async def test_direct_runtime_commits_message_snapshot() -> None:
    service = _PersistenceService()
    runtime = DirectChatRuntime(service)  # type: ignore[arg-type]
    metadata = {"usage": {"total_tokens": 12}}

    await runtime._persist_message_snapshot(
        "message-1", "partial response", "streaming", metadata
    )

    service.update_message_content.assert_awaited_once_with(
        "message-1", "partial response", "streaming", metadata
    )
    service._commit_stream_anchor.assert_awaited_once()
