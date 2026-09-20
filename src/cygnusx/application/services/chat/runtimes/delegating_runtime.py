"""逐步迁移期间复用既有 Agent 流程的 Runtime 基类。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cygnusx.application.services.chat.runtimes.base import ChatRuntime, ChatRuntimeRequest
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

if TYPE_CHECKING:
    from cygnusx.application.services.chat_service import ChatService


class DelegatingAgentRuntime(ChatRuntime):
    """将标准 Runtime 请求无损转交给既有生成器。"""

    def __init__(self, service: ChatService) -> None:
        self._service = service

    async def run(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]:
        async for chunk in self._service._stream_agent_chat_inner(
            request.user_id,
            request.agent_id,
            request.messages,
            session_id=request.session_id,
            model_id=request.model_id,
            attachments=request.attachments,
            enable_web_search=request.enable_web_search,
            enable_code_execution=request.enable_code_execution,
            deep_thinking=request.deep_thinking,
            mode=request.mode,
            runtime_profile=request.runtime_profile,
            mcp_mode=request.mcp_mode,
            extra_mcp_servers=request.extra_mcp_servers,
            multi_agent=request.multi_agent,
            overdrive=request.overdrive,
            extend_max_rounds=request.extend_max_rounds,
            project_id=request.project_id,
            runtime_context=request.runtime_context,
            auto_approve=request.auto_approve,
        ):
            yield chunk
