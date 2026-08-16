"""LLM Provider 抽象接口"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class StreamEvent:
    """流式事件统一抽象 — 供 stream_chat_with_tools 使用

    type:
      - "text": 内容 token（content 非空）
      - "tool_calls": 工具调用组装完毕（tool_calls 非空，OpenAI tool_calls 格式）
      - "done": 流结束
    """

    type: str  # "text" | "tool_calls" | "done"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    """LLM 提供者统一接口"""

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """非流式对话；传入 tools 时返回可能包含 tool_calls"""
        ...

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """流式对话 - 逐 token 返回（async generator，调用无需 await）"""
        ...

    async def is_configured(self) -> bool:
        """检查是否已配置有效 API Key 与模型"""
        ...

    async def embeddings(self, text: str, model: str = "") -> list[float]:
        """文本嵌入向量"""
        ...

    # 可选：流式 + 工具调用（支持 FC 的 provider 实现）
    # AIService 用 getattr(provider, 'stream_chat_with_tools', None) 检测
    async def stream_chat_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式对话 + 工具调用 — 逐 token 推送 + 流末组装 tool_calls"""
        ...
