"""直连聊天 Runtime 入口测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from cygnusx.application.services.chat.direct_chat_entrypoint import DirectChatEntrypoint
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


@pytest.mark.asyncio
async def test_direct_entrypoint_builds_normalized_runtime_request(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _Router:
        def __init__(self, service: object) -> None:
            captured["service"] = service

        async def stream(self, request: Any) -> AsyncIterator[ChatChunk]:
            captured["request"] = request
            yield ChatChunk(type="done")

    monkeypatch.setattr(
        "cygnusx.application.services.chat.direct_chat_entrypoint.ChatRouterService",
        _Router,
    )
    entrypoint = DirectChatEntrypoint()
    model_id = uuid4()

    chunks = [
        chunk
        async for chunk in entrypoint.stream_chat(
            user_id="user-1",
            messages=[{"role": "user", "content": "hello"}],
            model_id=model_id,
            session_id="session-1",
            assistant_id="assistant-1",
            system_prompt="system",
            temperature=0.4,
            max_tokens=123,
            enable_web_search=True,
            project_id="project-1",
        )
    ]

    request = captured["request"]
    assert captured["service"] is entrypoint
    assert [chunk.type for chunk in chunks] == ["done"]
    assert request.agent_id == "direct-chat"
    assert request.model_id == model_id
    assert request.enable_web_search is True
    assert request.runtime_context == {
        "runtime": "direct",
        "assistant_id": "assistant-1",
        "system_prompt": "system",
        "temperature": 0.4,
        "max_tokens": 123,
    }
