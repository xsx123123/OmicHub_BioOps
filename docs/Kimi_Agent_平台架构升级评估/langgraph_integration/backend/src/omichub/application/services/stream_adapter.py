"""
StreamAdapter
==============
LangGraph 事件流 → OmicHub SSE 格式适配器。

职责:
    - 将 LangGraphRuntimeService 生成的事件转换为 SSEEvent
    - 保持与现有 useAgentChatStream.ts 的格式兼容
    - 新增 hitl_request / hitl_resumed 事件类型
    - 支持打字机效果（text 事件分片）

设计:
    - 纯函数，无状态，便于测试
    - 每个事件类型有独立转换函数
    - 支持自定义事件转换器（扩展用）
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Dict, Optional

from omichub.infrastructure.execution.langgraph_runtime import SSEEvent


class StreamAdapter:
    """
    LangGraph 事件 → OmicHub SSE 事件适配器

    兼容事件类型:
        - text:         文本块（打字机）
        - tool_call:    工具调用开始
        - tool_result:  工具执行结果
        - hitl_request: HITL 中断请求（新增）
        - hitl_resumed: HITL 恢复通知（新增）
        - status:       状态更新
        - done:         完成
        - error:        错误
    """

    def __init__(self):
        self._custom_converters: Dict[str, Callable] = {}

    def register_converter(self, event_type: str, converter: Callable) -> None:
        """注册自定义事件转换器"""
        self._custom_converters[event_type] = converter

    async def adapt(
        self,
        event: Dict[str, Any],
    ) -> Optional[SSEEvent]:
        """
        将 LangGraph 事件转换为 SSEEvent

        Args:
            event: {"type": str, "data": dict, "state": AgentState}

        Returns:
            SSEEvent 或 None（不转换的事件）
        """
        event_type = event.get("type", "")
        data = event.get("data", {})
        state = event.get("state")

        # 自定义转换器优先
        if event_type in self._custom_converters:
            return self._custom_converters[event_type](event)

        # 内置转换
        converter = self._converters.get(event_type)
        if converter:
            return converter(data)

        return None

    async def adapt_stream(
        self,
        events: AsyncIterator[Dict[str, Any]],
    ) -> AsyncIterator[str]:
        """
        适配整个事件流，生成 SSE 格式字符串

        Yields:
            SSE 格式字符串: "event: xxx\ndata: {...}\n\n"
        """
        async for event in events:
            sse_event = await self.adapt(event)
            if sse_event:
                yield sse_event.to_sse_string()

    # ── 内置转换器 ──

    @property
    def _converters(self) -> Dict[str, Callable]:
        return {
            "text": self._convert_text,
            "tool_call": self._convert_tool_call,
            "tool_result": self._convert_tool_result,
            "hitl_request": self._convert_hitl_request,
            "hitl_resumed": self._convert_hitl_resumed,
            "status": self._convert_status,
            "done": self._convert_done,
            "error": self._convert_error,
        }

    @staticmethod
    def _convert_text(data: Dict[str, Any]) -> SSEEvent:
        """文本事件 —— 打字机效果"""
        return SSEEvent.text(
            content=data.get("content", ""),
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_tool_call(data: Dict[str, Any]) -> SSEEvent:
        """工具调用事件"""
        return SSEEvent.tool_call(
            tool_name=data.get("tool_name", ""),
            tool_input=data.get("tool_input", {}),
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_tool_result(data: Dict[str, Any]) -> SSEEvent:
        """工具结果事件"""
        return SSEEvent.tool_result(
            tool_name=data.get("tool_name", ""),
            result=data.get("result", ""),
            success=data.get("success", True),
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_hitl_request(data: Dict[str, Any]) -> SSEEvent:
        """HITL 中断请求事件（前端收到后渲染弹窗）"""
        payload = data.get("payload", {})
        return SSEEvent.hitl_request(
            payload=payload,
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_hitl_resumed(data: Dict[str, Any]) -> SSEEvent:
        """HITL 恢复事件"""
        return SSEEvent.hitl_resumed(
            action=data.get("action", ""),
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_status(data: Dict[str, Any]) -> SSEEvent:
        """状态更新事件"""
        return SSEEvent.status(
            phase=data.get("phase", ""),
            detail=data.get("detail", ""),
            thread_id=data.get("thread_id", ""),
        )

    @staticmethod
    def _convert_done(data: Dict[str, Any]) -> SSEEvent:
        """完成事件"""
        return SSEEvent.done(
            response=data.get("content", ""),
            thread_id=data.get("thread_id", ""),
            metadata=data.get("metadata"),
        )

    @staticmethod
    def _convert_error(data: Dict[str, Any]) -> SSEEvent:
        """错误事件"""
        return SSEEvent.error(
            message=data.get("message", "未知错误"),
            thread_id=data.get("thread_id", ""),
        )


# ──────────────────────────────
# 便捷函数
# ──────────────────────────────

def create_sse_response(
    runtime_stream: AsyncIterator[Dict[str, Any]],
    adapter: Optional[StreamAdapter] = None,
) -> AsyncIterator[str]:
    """
    创建 SSE 响应流 —— 直接用于 FastAPI StreamingResponse

    用法:
        @router.post("/chat/stream")
        async def chat_stream(req: ChatRequest):
            stream = langgraph_runtime.stream(initial_state)
            return StreamingResponse(
                create_sse_response(stream),
                media_type="text/event-stream",
            )
    """
    _adapter = adapter or StreamAdapter()
    return _adapter.adapt_stream(runtime_stream)
