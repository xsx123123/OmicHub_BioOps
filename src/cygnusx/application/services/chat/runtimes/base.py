"""所有聊天 Runtime 共用的事件状态机基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from cygnusx.application.services.execution_events import execution_chunk
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


@dataclass(frozen=True)
class ChatRuntimeRequest:
    """Runtime 选择完成后不可变的单轮聊天输入。"""

    user_id: str
    agent_id: str
    messages: list[dict[str, str]]
    session_id: str | None = None
    model_id: UUID | None = None
    attachments: list[dict[str, Any]] | None = None
    enable_web_search: bool = False
    enable_code_execution: bool = False
    deep_thinking: bool = False
    mode: str | None = None
    runtime_profile: str | None = None
    mcp_mode: str | None = None
    extra_mcp_servers: list[str] | None = None
    multi_agent: bool | None = None
    overdrive: bool | None = None
    extend_max_rounds: bool = False
    project_id: str | None = None
    runtime_context: dict[str, Any] = field(default_factory=dict)
    auto_approve: bool | None = None


class ChatRuntime(ABC):
    """Runtime 只能从 ``run`` 生成事件，构造方法不得 yield。"""

    @abstractmethod
    async def run(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]:
        """执行一个用户回合并按公共事件契约流式输出。"""
        yield ChatChunk(type="done")

    @staticmethod
    def _execution_identifiers(context: Any) -> dict[str, Any]:
        return {
            "session_id": str(getattr(context, "session_id", "")),
            "run_id": str(getattr(context, "run_id", "")),
            "agent_id": str(context.agent.agent_id),
            "round_number": int(getattr(context, "round_number", 1)),
            "execution_path": str(getattr(context, "execution_path", "chat_runtime")),
        }

    def _build_turn_started(self, context: Any) -> ChatChunk:
        return execution_chunk("agent_turn_started", **self._execution_identifiers(context))

    def _build_context_reinjected(self, context: Any, tool_call_id: str) -> ChatChunk:
        return execution_chunk(
            "agent_context_reinjected",
            **self._execution_identifiers(context),
            tool_call_id=tool_call_id,
        )

    def _build_turn_continued(self, context: Any) -> ChatChunk:
        return execution_chunk("agent_turn_continued", **self._execution_identifiers(context))

    def _build_final(self, context: Any, final_text: str) -> ChatChunk:
        return execution_chunk(
            "agent_final_result", content=final_text, **self._execution_identifiers(context)
        )

    def _build_ask_user(self, context: Any, prompt: str) -> ChatChunk:
        return execution_chunk(
            "ask_user", content=prompt, **self._execution_identifiers(context)
        )

    def _build_handoff(self, context: Any, target_agent_id: str) -> ChatChunk:
        return execution_chunk(
            "handoff",
            **self._execution_identifiers(context),
            target_agent_id=target_agent_id,
        )

    def _build_failed(self, context: Any, error: str) -> ChatChunk:
        return execution_chunk(
            "agent_turn_failed", content=error, **self._execution_identifiers(context), error=error
        )

    def _build_done(self, context: Any) -> ChatChunk:
        return ChatChunk(type="done", metadata=self._execution_identifiers(context))
