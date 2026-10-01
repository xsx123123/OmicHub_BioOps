import asyncio
from types import SimpleNamespace

import pytest

from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.execution.langgraph_nodes import NodeDeps, llm_call_node
from cygnusx.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService


@pytest.mark.asyncio
async def test_langgraph_llm_call_uses_compacted_provider_view() -> None:
    calls: list[list[dict]] = []
    emitted: list[ChatChunk] = []

    async def stream(**kwargs):
        calls.append(kwargs["messages"])
        yield ChatChunk(type="text", content="done")
        yield ChatChunk(type="done", metadata={})

    async def prepare(messages):
        assert messages == [{"role": "user", "content": "original"}]
        return ([{"role": "system", "content": "handoff"}], True, 42)

    async def emit(chunk):
        emitted.append(chunk)

    deps = NodeDeps(
        model_config=SimpleNamespace(model="test"),
        chat_stream=stream,
        emit=emit,
        session_id="session-1",
        message_id="message-1",
        prepare_messages=prepare,
    )
    delta = await llm_call_node(
        {"messages": [{"role": "user", "content": "original"}], "rounds": 0},
        deps,
    )

    assert calls == [[{"role": "system", "content": "handoff"}]]
    assert delta["messages"] == [{"role": "assistant", "content": "done"}]
    assert emitted[0].type == "context_compressed"
    assert emitted[0].metadata == {
        "session_id": "session-1",
        "message_id": "message-1",
        "estimated_tokens_before": 42,
    }


@pytest.mark.asyncio
async def test_langgraph_runtime_preserves_thirty_tool_rounds_with_compacted_views() -> None:
    provider_rounds = 0
    prepare_inputs: list[list[dict]] = []
    provider_views: list[list[dict]] = []
    emitted: list[ChatChunk] = []

    async def stream(**kwargs):
        nonlocal provider_rounds
        provider_rounds += 1
        provider_views.append(kwargs["messages"])
        if provider_rounds <= 30:
            yield ChatChunk(
                type="tool_calls",
                metadata={
                    "tool_calls": [
                        {
                            "id": f"call-{provider_rounds}",
                            "type": "function",
                            "function": {"name": "echo", "arguments": "{}"},
                        }
                    ]
                },
            )
        else:
            yield ChatChunk(type="text", content="最终答复")
        yield ChatChunk(type="done", metadata={})

    async def prepare(messages):
        prepare_inputs.append(messages)
        if len(messages) <= 10:
            return messages, False, len(messages)
        return [messages[0], *messages[-4:]], True, len(messages)

    async def tool_executor(_name, _args, call_id):
        return {"success": True, "result": {"call_id": call_id, "content": "工具结果"}}

    async def emit(chunk):
        emitted.append(chunk)

    deps = NodeDeps(
        model_config=SimpleNamespace(model="test"),
        chat_stream=stream,
        tool_executor=tool_executor,
        prepare_messages=prepare,
        emit=emit,
    )
    runtime = LangGraphRuntimeService(deps, max_rounds=30)

    async def collect():
        return [
            chunk
            async for chunk in runtime.stream(
                [{"role": "user", "content": "中文目标"}]
            )
        ]

    chunks = await asyncio.wait_for(collect(), timeout=10)

    assert runtime.error is None
    assert provider_rounds == 31
    assert len(prepare_inputs) == 31
    assert any(chunk.type == "context_compressed" for chunk in chunks)
    assert any(len(view) < len(source) for view, source in zip(provider_views, prepare_inputs))
    assert runtime.last_messages[0]["content"] == "中文目标"
    assert len(runtime.last_messages) == 62
    assert sum(chunk.type == "tool_result" for chunk in chunks) == 30
    assert chunks[-1].type == "text"


@pytest.mark.asyncio
async def test_langgraph_provider_request_survives_compaction_failure(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    settings = SimpleNamespace(
        storage_path=str(tmp_path),
        context_compaction=SimpleNamespace(
            trigger_ratio=0.1,
            large_output_chars=16_384,
            preview_chars=768,
            keep_recent_min=2,
            tail_ratio=0.25,
            min_yield_ratio=0.1,
            breaker_attempts=2,
            circuit_retry_growth=1.5,
            min_messages=2,
            summary_max_chars=6000,
            legacy_fallback=False,
        ),
    )
    monkeypatch.setattr(runtime_support, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_support,
        "externalize_large_outputs",
        lambda messages, *_args, **_kwargs: (list(messages), 0),
    )

    async def failing_summary(*_args, **_kwargs):
        raise RuntimeError("summary provider unavailable")

    monkeypatch.setattr(runtime_support, "compact", failing_summary)
    support = runtime_support.ChatRuntimeSupport()
    support._active_context_session_id = "langgraph-failure-fallback"
    model = SimpleNamespace(context_window=20, model="test", max_tokens=128)
    provider_calls = 0

    async def provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        yield ChatChunk(type="text", content="请求继续完成")
        yield ChatChunk(type="done", metadata={})

    async def prepare(messages):
        return await support._compress_context_if_needed(messages, model)

    deps = NodeDeps(
        model_config=model,
        chat_stream=provider,
        prepare_messages=prepare,
    )
    runtime = LangGraphRuntimeService(deps, max_rounds=2)
    chunks = [
        chunk
        async for chunk in runtime.stream(
            [{"role": "user", "content": f"message-{index}"} for index in range(10)]
        )
    ]

    assert provider_calls == 1
    assert runtime.error is None
    assert [chunk.content for chunk in chunks if chunk.type == "text"] == ["请求继续完成"]
    assert not any(chunk.type == "error" for chunk in chunks)
