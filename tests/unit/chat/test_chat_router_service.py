"""Runtime 路由灰度骨架测试。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from cygnusx.application.services.chat.chat_router_service import ChatRouterService
from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest
from cygnusx.application.services.chat.runtimes.direct_chat_runtime import DirectChatRuntime
from cygnusx.application.services.chat.runtimes.langgraph_runtime import LangGraphChatRuntime
from cygnusx.application.services.chat.runtimes.legacy_runtime import LegacyChatRuntime
from cygnusx.application.services.chat.runtimes.overdrive_runtime import OverdriveChatRuntime
from cygnusx.application.services.chat.runtimes.studio_runtime import StudioChatRuntime
from cygnusx.application.services.chat_service import ChatService
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class _LegacyService:
    async def _stream_agent_chat_inner(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatChunk]:
        del args, kwargs
        yield ChatChunk(type="text", content="ok")
        yield ChatChunk(type="done")


class _RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def _stream_agent_chat_inner(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append((args, kwargs))
        yield ChatChunk(type="done")


@pytest.mark.asyncio
async def test_router_uses_legacy_adapter_until_a_specific_runtime_is_migrated() -> None:
    service = _LegacyService()
    request = ChatRuntimeRequest(user_id="user-1", agent_id="agent-1", messages=[])
    router = ChatRouterService(service)  # type: ignore[arg-type]

    assert isinstance(router.select_runtime(request), LegacyChatRuntime)
    assert [chunk.type async for chunk in router.stream(request)] == ["text", "done"]


def test_router_selects_direct_runtime_for_migrated_direct_requests() -> None:
    service = _LegacyService()
    request = ChatRuntimeRequest(
        user_id="user-1",
        agent_id="direct-chat",
        messages=[],
        runtime_context={"runtime": "direct"},
    )

    assert isinstance(ChatRouterService(service).select_runtime(request), DirectChatRuntime)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("runtime_request", "runtime_type"),
    [
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-1",
                messages=[],
                mode="studio",
            ),
            StudioChatRuntime,
        ),
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-1",
                messages=[],
                overdrive=True,
            ),
            OverdriveChatRuntime,
        ),
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-1",
                messages=[],
                runtime_context={"runtime": "langgraph"},
            ),
            LangGraphChatRuntime,
        ),
    ],
)
def test_router_selects_explicit_migrating_runtime(
    runtime_request: ChatRuntimeRequest,
    runtime_type: type[object],
) -> None:
    service = _LegacyService()

    assert isinstance(ChatRouterService(service).select_runtime(runtime_request), runtime_type)  # type: ignore[arg-type]


def test_langgraph_stream_loop_is_owned_by_runtime() -> None:
    assert "_stream_agent_chat_langgraph" in LangGraphChatRuntime.__dict__
    assert "_stream_agent_chat_langgraph" not in ChatService.__dict__


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runtime_request",
    [
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            mode="studio",
            project_id="project-1",
        ),
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            overdrive=True,
            runtime_context={"runtime": "langgraph"},
            project_id="project-1",
        ),
    ],
)
async def test_delegating_runtimes_forward_full_request(
    runtime_request: ChatRuntimeRequest,
) -> None:
    service = _RecordingService()

    assert [chunk.type async for chunk in ChatRouterService(service).stream(runtime_request)] == ["done"]  # type: ignore[arg-type]
    args, kwargs = service.calls[0]
    assert args == ("user-1", "agent-1", [{"role": "user", "content": "hello"}])
    assert kwargs["mode"] == runtime_request.mode
    assert kwargs["overdrive"] == runtime_request.overdrive
    assert kwargs["project_id"] == "project-1"
    assert kwargs["runtime_context"] == runtime_request.runtime_context
