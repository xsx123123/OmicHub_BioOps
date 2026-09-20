"""直连模型聊天的统一 Runtime 入口。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from cygnusx.application.services.chat.chat_router_service import ChatRouterService
from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class DirectChatEntrypoint:
    """将直连聊天请求规范化后交由 Runtime 路由器处理。"""

    async def stream_chat(
        self,
        user_id: str,
        messages: list[dict[str, str]],
        model_id: uuid.UUID,
        session_id: str | None = None,
        assistant_id: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_web_search: bool = False,
        project_id: str | None = None,
        page_context: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        runtime_context: dict[str, Any] = {
            "runtime": "direct",
            "assistant_id": assistant_id,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if page_context:
            runtime_context["page_context"] = page_context
        request = ChatRuntimeRequest(
            user_id=user_id,
            agent_id="direct-chat",
            messages=messages,
            model_id=model_id,
            session_id=session_id,
            enable_web_search=enable_web_search,
            project_id=project_id,
            runtime_context=runtime_context,
        )
        async for chunk in ChatRouterService(self).stream(request):
            yield chunk
