"""Agent 聊天 Runtime 的统一入口与观测网关。"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from cygnusx.application.services.chat.chat_router_service import ChatRouterService
from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest
from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter, get_tracer
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

_agent_duration = get_meter("cygnusx.chat").create_histogram(
    "agent.run.duration", unit="ms", description="Agent 单次运行耗时"
)
_legacy_runtime_entry_count = get_meter("cygnusx.chat").create_counter(
    "agent.runtime.legacy_entry.count",
    description="仍通过旧 Agent 编排入口的调用次数",
)


class AgentRuntimeGateway:
    """统一构造 Agent Runtime 请求并提供执行观测。"""

    async def stream_agent_chat(
        self,
        user_id: str,
        agent_id: str,
        messages: list[dict[str, str]],
        session_id: str | None = None,
        model_id: uuid.UUID | None = None,
        attachments: list[dict[str, Any]] | None = None,
        enable_web_search: bool = False,
        enable_code_execution: bool = False,
        deep_thinking: bool = False,
        mode: str | None = None,
        runtime_profile: str | None = None,
        mcp_mode: str | None = None,
        extra_mcp_servers: list[str] | None = None,
        multi_agent: bool | None = None,
        overdrive: bool | None = None,
        extend_max_rounds: bool = False,
        project_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
        page_context: str | None = None,
        auto_approve: bool | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Agent 编排入口（带 Trace/Log/Metrics 埋点）：作为 AI/MCP/技能 span 的父 span。"""
        tracer = get_tracer("cygnusx.chat")
        span_attrs: dict[str, Any] = {"agent.id": agent_id}
        if model_id is not None:
            span_attrs["agent.model_id"] = str(model_id)
        # 本函数是异步生成器，若消费方在不同 asyncio Task 中推进 anext（各自 copy
        # Context），with 退出时 OTel detach / ContextVar reset 会跨 Context 抛
        # "Token was created in a different Context"。手动 enter/exit + 值式恢复 +
        # suppress 退出异常，保证任何消费方式下流都能正常收尾。
        span_cm = tracer.start_as_current_span("agent.run", attributes=span_attrs)
        span = span_cm.__enter__()
        # 把 agent.run 的 span context 发布到 ContextVar：LangGraph 图任务等跨
        # asyncio task 边界的子 span 在 contextvars 链路丢失时可显式取回父
        # context（见 infrastructure/execution/langgraph_runtime.py）。
        from opentelemetry import trace as _otel_trace

        from cygnusx.core.telemetry import agent_parent_context_var

        previous_parent_ctx = agent_parent_context_var.get()
        agent_parent_context_var.set(_otel_trace.set_span_in_context(span))
        start = time.perf_counter()
        status = "success"
        try:
            # 页面上下文经 runtime_context 透传给 Runtime，由系统提示词组装处统一注入
            effective_runtime_context = dict(runtime_context or {})
            if page_context:
                effective_runtime_context["page_context"] = page_context
            request = ChatRuntimeRequest(
                user_id=user_id,
                agent_id=agent_id,
                messages=messages,
                session_id=session_id,
                model_id=model_id,
                attachments=attachments,
                enable_web_search=enable_web_search,
                enable_code_execution=enable_code_execution,
                deep_thinking=deep_thinking,
                mode=mode,
                runtime_profile=runtime_profile,
                mcp_mode=mcp_mode,
                extra_mcp_servers=extra_mcp_servers,
                multi_agent=multi_agent,
                overdrive=overdrive,
                extend_max_rounds=extend_max_rounds,
                project_id=project_id,
                runtime_context=effective_runtime_context,
                auto_approve=auto_approve,
            )
            settings = get_settings()
            if settings.chat_runtime_refactor_enabled:
                stream = ChatRouterService(self).stream(request)
            else:
                legacy_attributes = {
                    "agent.id": agent_id,
                    "chat.mode": mode or "chat",
                }
                _legacy_runtime_entry_count.add(1, legacy_attributes)
                logger.bind(
                    event="agent.runtime.legacy_entry",
                    **legacy_attributes,
                ).info("agent runtime used legacy entry")
                stream = self._stream_agent_chat_inner(
                    user_id,
                    agent_id,
                    messages,
                    session_id=session_id,
                    model_id=model_id,
                    attachments=attachments,
                    enable_web_search=enable_web_search,
                    enable_code_execution=enable_code_execution,
                    deep_thinking=deep_thinking,
                    mode=mode,
                    runtime_profile=runtime_profile,
                    mcp_mode=mcp_mode,
                    extra_mcp_servers=extra_mcp_servers,
                    multi_agent=multi_agent,
                    overdrive=overdrive,
                    extend_max_rounds=extend_max_rounds,
                    project_id=project_id,
                    runtime_context=effective_runtime_context,
                    auto_approve=auto_approve,
                )
            async for chunk in stream:
                if chunk.type == "error":
                    status = "error"
                yield chunk
        except Exception as exc:  # noqa: BLE001
            status = "error"
            span.record_exception(exc)
            with contextlib.suppress(Exception):
                span.set_status(_otel_trace.Status(_otel_trace.StatusCode.ERROR, str(exc)))
            raise
        finally:
            with contextlib.suppress(Exception):
                agent_parent_context_var.set(previous_parent_ctx)
            duration_ms = (time.perf_counter() - start) * 1000
            attrs = {"agent.id": agent_id, "agent.status": status}
            span.set_attribute("agent.status", status)
            span.set_attribute("agent.duration_ms", round(duration_ms, 2))
            with contextlib.suppress(Exception):
                _agent_duration.record(duration_ms, attrs)
            logger.bind(
                event="agent.run",
                agent_id=agent_id,
                status=status,
                duration_ms=round(duration_ms, 2),
            ).info("agent.run completed")
            with contextlib.suppress(Exception):
                span_cm.__exit__(None, None, None)
