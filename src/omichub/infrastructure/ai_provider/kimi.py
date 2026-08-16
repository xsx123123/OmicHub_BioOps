"""Kimi API (Moonshot) 适配器"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from omichub.core.config import get_settings
from omichub.infrastructure.ai_provider.base import StreamEvent


class KimiProvider:
    """Kimi API 适配器 - 实现 LLMProvider 接口"""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.kimi_base_url
        self.api_key = settings.kimi_api_key
        self.model = settings.kimi_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """同步对话"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": model or self.model,
                    "messages": messages,
                    "temperature": temperature,
                    **({"tools": tools} if tools else {}),
                },
                timeout=120,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """流式对话"""
        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": model or self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
                timeout=120,
            ) as response,
        ):
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk["choices"][0]["delta"].get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def is_configured(self) -> bool:
        """检查是否已配置有效 API Key 与模型"""
        return bool(self.api_key) and bool(self.model)

    async def stream_chat_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """降级实现：非流式 chat + 整段 content 作单条 StreamEvent

        Kimi 旧版 API 不支持 stream+tools，委托非流式后封装为事件流。
        """
        response = await self.chat(messages, model=model, temperature=temperature, tools=tools)
        message = response.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "") or ""
        if content:
            yield StreamEvent(type="text", content=content)
        raw_tool_calls = message.get("tool_calls") or []
        if raw_tool_calls:
            yield StreamEvent(type="tool_calls", tool_calls=raw_tool_calls)
        yield StreamEvent(type="done")

    async def embeddings(self, text: str, model: str = "") -> list[float]:
        """文本嵌入向量（Kimi 当前无嵌入接口，返回空列表占位）"""
        return []
