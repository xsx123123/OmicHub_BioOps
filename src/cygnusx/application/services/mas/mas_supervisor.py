"""Supervisor 决策 LLM 构建（适配层，不改既有 provider 代码）。

Supervisor 用轻量非流式决策调用：复用 OpenAICompatibleProvider.chat_stream，
收集最终文本返回（不透传 SSE——Supervisor 的决策以 mas_trace 消息落库）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def build_supervisor_llm() -> Any:
    """返回 async callable(messages) -> str（Supervisor 决策调用）。

    模型缺失/未启用时返回 None；mas_graph 对 None 走"自己直接回答"兜底。
    """
    from cygnusx.infrastructure.ai_provider.openai_compatible import OpenAICompatibleProvider
    from cygnusx.infrastructure.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel

        result = await session.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.is_active == True  # noqa: E712
            )
        )
        configs = list(result.scalars().all())
    if not configs:
        return None

    async def supervisor_call(messages: list[dict[str, Any]]) -> str:
        """按 provider 顺序尝试（默认优先），全部失败抛最后一个错误。"""
        last_error: Exception | None = None
        ordered = [c for c in configs if c.is_default] + [
            c for c in configs if not c.is_default
        ]
        for config in ordered:
            provider = OpenAICompatibleProvider(config)
            parts: list[str] = []
            try:
                async for chunk in provider.chat_stream(
                    [
                        {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
                        for m in messages
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                ):
                    if chunk.type == "text" and chunk.content:
                        parts.append(chunk.content)
                    elif chunk.type == "error":
                        raise RuntimeError(chunk.content)
                text = "".join(parts).strip()
                if text:
                    return text
            except Exception as exc:  # noqa: BLE001 - 尝试下一个 provider
                logger.warning("MAS supervisor provider %s failed: %s", config.name, exc)
                last_error = exc
        raise last_error or RuntimeError("无可用 AI Provider")

    return supervisor_call
