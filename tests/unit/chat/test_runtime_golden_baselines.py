"""非受保护 Chat Runtime 的可复现 SSE golden 基线。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cygnusx.application.services.chat.chat_router_service import ChatRouterService
from cygnusx.application.services.chat.dual_run import (
    assert_equivalent,
    compare_golden_record,
    compare_streams,
)
from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest
from cygnusx.application.services.chat.runtimes.direct_chat_runtime import DirectChatRuntime
from cygnusx.application.services.execution_events import validate_event_sequence
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


_GOLDEN_ROOT = Path(__file__).parents[2] / "e2e" / "chat_golden"


class _GoldenService:
    async def _stream_agent_chat_inner(
        self, *_: object, **__: object
    ) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(
            type="agent_turn_started",
            metadata={
                "session_id": "session-random",
                "run_id": "run-random",
                "agent_id": "agent-general",
                "round_number": 1,
            },
        )
        yield ChatChunk(
            type="tool_call",
            metadata={
                "tool_call_id": "tool-random",
                "tool_name": "knowledge_search",
                "arguments": {"query": "TP53"},
            },
        )
        yield ChatChunk(
            type="tool_result",
            metadata={
                "tool_call_id": "tool-random",
                "success": True,
                "result": {"hits": 1},
            },
        )
        yield ChatChunk(
            type="agent_context_reinjected",
            metadata={
                "session_id": "session-random",
                "run_id": "run-random",
                "agent_id": "agent-general",
                "round_number": 1,
                "tool_call_id": "tool-random",
            },
        )
        yield ChatChunk(
            type="agent_turn_continued",
            metadata={
                "session_id": "session-random",
                "run_id": "run-random",
                "agent_id": "agent-general",
                "round_number": 1,
            },
        )
        yield ChatChunk(
            type="agent_final_result",
            content="TP53 是抑癌基因。",
            metadata={"session_id": "session-random", "agent_id": "agent-general"},
        )
        yield ChatChunk(type="done", metadata={"run_id": "run-random"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_request", "golden_name"),
    [
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-general",
                messages=[{"role": "user", "content": "解释 TP53"}],
            ),
            "legacy-tool-round.json",
        ),
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-general",
                messages=[{"role": "user", "content": "解释 TP53"}],
                mode="studio",
            ),
            "studio-tool-round.json",
        ),
        (
            ChatRuntimeRequest(
                user_id="user-1",
                agent_id="agent-general",
                messages=[{"role": "user", "content": "解释 TP53"}],
                overdrive=True,
            ),
            "overdrive-tool-round.json",
        ),
    ],
)
async def test_router_runtime_matches_committed_golden_record(
    runtime_request: ChatRuntimeRequest,
    golden_name: str,
) -> None:
    router = ChatRouterService(_GoldenService())  # type: ignore[arg-type]
    result = await compare_golden_record(
        golden_name,
        _GOLDEN_ROOT / golden_name,
        lambda: router.stream(runtime_request),
    )

    assert_equivalent([result])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runtime_request",
    [
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
        ),
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
            mode="studio",
        ),
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
            overdrive=True,
        ),
    ],
)
async def test_router_runtime_matches_legacy_stream_in_dual_run(
    runtime_request: ChatRuntimeRequest,
) -> None:
    service = _GoldenService()
    router = ChatRouterService(service)  # type: ignore[arg-type]
    result = await compare_streams(
        "router-runtime-dual-run",
        lambda: service._stream_agent_chat_inner(
            runtime_request.user_id,
            runtime_request.agent_id,
            runtime_request.messages,
        ),
        lambda: router.stream(runtime_request),
    )

    assert_equivalent([result])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runtime_request",
    [
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
        ),
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
            mode="studio",
        ),
        ChatRuntimeRequest(
            user_id="user-1",
            agent_id="agent-general",
            messages=[{"role": "user", "content": "解释 TP53"}],
            overdrive=True,
        ),
    ],
)
async def test_router_runtime_golden_stream_satisfies_execution_state_machine(
    runtime_request: ChatRuntimeRequest,
) -> None:
    router = ChatRouterService(_GoldenService())  # type: ignore[arg-type]
    chunks = [chunk async for chunk in router.stream(runtime_request)]

    validate_event_sequence(chunks)


@pytest.mark.asyncio
async def test_direct_runtime_input_error_matches_committed_golden_record() -> None:
    runtime = DirectChatRuntime(object())  # type: ignore[arg-type]
    request = ChatRuntimeRequest(user_id="user-1", agent_id="direct-chat", messages=[])
    result = await compare_golden_record(
        "direct-missing-model.json",
        _GOLDEN_ROOT / "direct-missing-model.json",
        lambda: runtime.run(request),
    )

    assert_equivalent([result])
