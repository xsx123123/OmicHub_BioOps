"""聊天 Runtime 选择入口。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cygnusx.application.services.chat.runtimes.base import ChatRuntime, ChatRuntimeRequest
from cygnusx.application.services.chat.runtimes.direct_chat_runtime import DirectChatRuntime
from cygnusx.application.services.chat.runtimes.langgraph_runtime import LangGraphChatRuntime
from cygnusx.application.services.chat.runtimes.legacy_runtime import LegacyChatRuntime
from cygnusx.application.services.chat.runtimes.overdrive_runtime import OverdriveChatRuntime
from cygnusx.application.services.chat.runtimes.studio_runtime import StudioChatRuntime
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

if TYPE_CHECKING:
    from cygnusx.application.services.chat_service import ChatService


class ChatRouterService:
    """根据请求选择已经完成迁移的 Runtime。"""

    def __init__(self, service: ChatService) -> None:
        self._service = service

    def select_runtime(self, request: ChatRuntimeRequest) -> ChatRuntime:
        """选择 Runtime。

        优先级：显式覆写（runtime_context["runtime"]，测试/灰度用，全库仅测试
        与调用方显式传入）> overdrive > studio > 普通聊天回落 Legacy。

        注意：单 Runtime 收敛（2026-09-19）后，普通聊天的 LangGraph 默认分流在
        ChatService._stream_agent_chat_inner 内部完成（不再以 features.engine
        为门）；此处回落的 LegacyChatRuntime 同样转发 _stream_agent_chat_inner，
        因此 Router 开与不开，普通聊天最终都进入 LangGraph 状态图（逃生舱
        engine:"legacy" / chat_force_legacy_runtime 除外）。
        """
        runtime = str(request.runtime_context.get("runtime") or "").lower()
        if runtime == "direct":
            return DirectChatRuntime(self._service)
        if runtime == "langgraph":
            return LangGraphChatRuntime(self._service)
        if request.overdrive:
            return OverdriveChatRuntime(self._service)
        if request.mode == "studio":
            return StudioChatRuntime(self._service)
        return LegacyChatRuntime(self._service)

    async def stream(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]:
        runtime = self.select_runtime(request)
        async for chunk in runtime.run(request):
            yield chunk
