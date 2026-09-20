"""trace context 传播单元测试

覆盖：
- inject_trace_context / extract_and_attach 的 headers roundtrip（含 session_id）；
- 无活跃 span / 空 headers 时的安全 no-op；
- Celery 信号接线（before_task_publish → task_prerun → task_postrun）；
- 同进程端到端：agent.run 父 span 下真实 LangGraphRuntimeService 的
  agent.tool_dispatch 子 span 必须 parent_span_id 非空且同 trace；
- contextvars 链路丢失时，图任务经 agent_parent_context_var 兜底恢复父子关系。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cygnusx.core.telemetry import (
    agent_parent_context_var,
    detach_extracted,
    extract_and_attach,
    inject_trace_context,
)
from cygnusx.middleware.trace_context import session_id_var


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exp = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    return exp


@pytest.fixture()
def tracer(exporter: InMemorySpanExporter) -> Any:  # noqa: ARG001
    return trace.get_tracer("test.trace-propagation")


def test_inject_extract_roundtrip(tracer: Any) -> None:
    """注入 traceparent + session_id 后，另一「进程」（空 context）可恢复。"""
    with tracer.start_as_current_span("parent") as parent:
        token = session_id_var.set("session-x")
        headers: dict[str, Any] = {}
        try:
            inject_trace_context(headers)
        finally:
            session_id_var.reset(token)
    parent_ctx = parent.get_span_context()

    assert "traceparent" in headers
    assert headers["x-cygnusx-session-id"] == "session-x"

    # 模拟对端进程：当前无任何活跃 span
    assert not trace.get_current_span().get_span_context().is_valid
    tokens = extract_and_attach(headers)
    try:
        extracted = trace.get_current_span().get_span_context()
        assert extracted.is_valid
        assert extracted.is_remote
        assert extracted.trace_id == parent_ctx.trace_id
        assert extracted.span_id == parent_ctx.span_id
        assert session_id_var.get() == "session-x"
    finally:
        detach_extracted(tokens)
    # 复位后回到无 span / 无 session 状态
    assert not trace.get_current_span().get_span_context().is_valid
    assert session_id_var.get() == ""


def test_extracted_context_parents_new_spans(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """worker 侧在提取的 context 下新建 span：同 trace 且 parent 指向派发方 span。"""
    with tracer.start_as_current_span("publisher") as pub:
        headers: dict[str, Any] = {}
        inject_trace_context(headers)
    exporter.clear()

    tokens = extract_and_attach(headers)
    try:
        with tracer.start_as_current_span("celery.task"):
            pass
    finally:
        detach_extracted(tokens)

    (span,) = exporter.get_finished_spans()
    assert span.name == "celery.task"
    assert span.context.trace_id == pub.get_span_context().trace_id
    assert span.parent is not None
    assert span.parent.span_id == pub.get_span_context().span_id


def test_noop_without_active_span_or_headers() -> None:
    """无活跃 span / 空 headers 时全部安全 no-op。"""
    headers: dict[str, Any] = {}
    inject_trace_context(headers)
    assert "traceparent" not in headers

    assert extract_and_attach(None) == (None, None)
    assert extract_and_attach({}) == (None, None)
    detach_extracted((None, None))  # 不抛异常
    inject_trace_context(None)  # 不抛异常


def test_celery_signal_wiring(tracer: Any) -> None:
    """信号接线后：发布注入 → prerun attach → postrun 复位。"""
    from celery.signals import before_task_publish, task_postrun, task_prerun

    from cygnusx.infrastructure.celery_app.tracing import wire_celery_tracing

    wire_celery_tracing()
    wire_celery_tracing()  # 幂等

    class _Request:
        def __init__(self, headers: dict[str, Any]) -> None:
            self.headers = headers

    class _Task:
        def __init__(self, headers: dict[str, Any]) -> None:
            self.request = _Request(headers)

    with tracer.start_as_current_span("publisher") as pub:
        token = session_id_var.set("session-celery")
        headers: dict[str, Any] = {}
        try:
            before_task_publish.send(sender="test.task", headers=headers)
        finally:
            session_id_var.reset(token)

    assert "traceparent" in headers
    assert headers["x-cygnusx-session-id"] == "session-celery"

    # ---- worker 侧 ----
    assert not trace.get_current_span().get_span_context().is_valid
    task = _Task(headers)
    task_prerun.send(sender=task)
    try:
        extracted = trace.get_current_span().get_span_context()
        assert extracted.is_valid
        assert extracted.trace_id == pub.get_span_context().trace_id
        assert session_id_var.get() == "session-celery"
    finally:
        task_postrun.send(sender=task)
    assert not trace.get_current_span().get_span_context().is_valid
    assert session_id_var.get() == ""


# ===== 同进程端到端：agent.run → LangGraph 图内子 span =====


def _tool_calls_chunk(name: str, args: dict[str, Any]) -> Any:
    from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

    return ChatChunk(
        type="tool_calls",
        metadata={
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ]
        },
    )


def _make_runtime() -> Any:
    from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
    from cygnusx.infrastructure.execution.langgraph_nodes import NodeDeps
    from cygnusx.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService

    calls = {"n": 0}

    async def _stream(**kwargs: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            yield _tool_calls_chunk("web_search", {"q": "x"})
        else:
            yield ChatChunk(type="text", content="完成")

    async def _executor(tool_name: str, args: dict[str, Any], tool_call_id: str) -> dict[str, Any]:  # noqa: ARG001
        return {"success": True, "result": {"value": 1}}

    deps = NodeDeps(
        model_config=None,
        chat_stream=_stream,
        tool_executor=_executor,
        channel_resolver=lambda name: None,
    )
    return LangGraphRuntimeService(deps, max_rounds=3)


async def _drive(runtime: Any) -> None:
    async for _ in runtime.stream([{"role": "user", "content": "hi"}]):
        pass


def _finished_by_name(exporter: InMemorySpanExporter, name: str) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.name == name]


async def test_tool_dispatch_is_child_of_agent_run(
    tracer: Any, exporter: InMemorySpanExporter
) -> None:
    """正常链路：agent.tool_dispatch 是 agent.run 的子 span（parent 非空、同 trace）。"""
    with tracer.start_as_current_span("agent.run") as parent:
        token = agent_parent_context_var.set(trace.set_span_in_context(parent))
        try:
            await _drive(_make_runtime())
        finally:
            agent_parent_context_var.reset(token)

    tools = _finished_by_name(exporter, "agent.tool_dispatch")
    assert len(tools) == 1
    parent_ctx = parent.get_span_context()
    assert tools[0].context.trace_id == parent_ctx.trace_id
    assert tools[0].parent is not None
    assert tools[0].parent.span_id == parent_ctx.span_id


async def test_graph_task_recovers_parent_when_contextvars_lost(
    tracer: Any, exporter: InMemorySpanExporter
) -> None:
    """模拟 asyncio task 边界丢失 contextvars：图任务经兜底 context 恢复父子关系。"""
    with tracer.start_as_current_span("agent.run") as parent:
        parent_ctx = trace.set_span_in_context(parent)
        parent_span_ctx = parent.get_span_context()

    # 模拟丢失后的环境：otel context 为空、只有网关发布的兜底 context
    lost_ctx = contextvars.Context()
    lost_ctx.run(agent_parent_context_var.set, parent_ctx)
    assert not lost_ctx.run(
        lambda: trace.get_current_span().get_span_context().is_valid
    )

    # 用丢失后的 context 创建 asyncio task 驱动图（等价于 task 边界断链场景）
    await asyncio.create_task(_drive(_make_runtime()), context=lost_ctx)

    tools = _finished_by_name(exporter, "agent.tool_dispatch")
    assert len(tools) == 1
    assert tools[0].context.trace_id == parent_span_ctx.trace_id
    assert tools[0].parent is not None
    assert tools[0].parent.span_id == parent_span_ctx.span_id
