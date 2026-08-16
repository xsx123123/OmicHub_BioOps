"""LangGraphRuntimeService：驱动 ReAct 状态图并产出 ChatChunk 流

图结构（对应 legacy 手写 ReAct 工具循环，轮数上限由 max_rounds 参数控制）：

    __start__ → llm_call ──[有 tool_calls]──→ tool_exec ──→ llm_call（回灌）
                     └──[无 tool_calls / 出错]──→ __end__

- 对外为 async generator，产出 text / tool_call / tool_result / error ChatChunk；
  不产 done —— 由调用方（ChatService）负责收尾落库与 done 事件。
- 事件透出用 asyncio.Queue：节点内 emit 实时入队，保证 text chunk 的打字机实时性。
- 图执行异常时产 error chunk 优雅结束，不向调用方抛错。
- 图结束后通过 last_usage / last_messages / error 暴露最终状态供调用方收尾。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

from langgraph.graph import END, StateGraph

from omichub.domain.execution.agent_state import AgentState
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk
from omichub.infrastructure.execution.langgraph_nodes import (
    NodeDeps,
    llm_call_node,
    route_after_llm,
    route_after_tool,
    tool_exec_node,
)


class LangGraphRuntimeService:
    """LangGraph 运行时服务 — 按请求构造（deps 内含会话级回调），非全局单例"""

    def __init__(self, deps: NodeDeps, max_rounds: int = 8) -> None:
        self._deps = deps
        self._max_rounds = max_rounds
        self._deps.max_tool_rounds = max_rounds
        self.last_usage: dict[str, Any] | None = None
        self.last_messages: list[dict[str, Any]] = []
        self.error: str | None = None
        self.last_handoff: dict[str, Any] | None = None
        self.last_ask_request: dict[str, Any] | None = None
        # 图因轮次触顶进入强制收尾轮时为 True，供调用方产出 round_limit 事件
        self.rounds_exhausted: bool = False
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        deps = self._deps
        max_rounds = self._max_rounds

        async def _llm_call(state: AgentState) -> dict[str, Any]:
            return await llm_call_node(state, deps)

        async def _tool_exec(state: AgentState) -> dict[str, Any]:
            return await tool_exec_node(state, deps)

        def _route_after_tool(state: AgentState) -> str:
            return route_after_tool(state, max_rounds)

        builder: StateGraph[AgentState] = StateGraph(AgentState)
        builder.add_node("llm_call", _llm_call)
        builder.add_node("tool_exec", _tool_exec)
        builder.set_entry_point("llm_call")
        builder.add_conditional_edges(
            "llm_call",
            route_after_llm,
            {"tool_exec": "tool_exec", "end": END},
        )
        builder.add_conditional_edges(
            "tool_exec",
            _route_after_tool,
            {"llm_call": "llm_call", "end": END},
        )
        return builder.compile()

    async def stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        """执行图，异步产出 ChatChunk（text/tool_call/tool_result/error）"""
        queue: asyncio.Queue[ChatChunk | None] = asyncio.Queue()

        async def _emit(chunk: ChatChunk) -> None:
            await queue.put(chunk)

        self._deps.emit = _emit
        initial: AgentState = {
            "messages": list(messages),
            "rounds": 0,
            "usage": None,
            "error": None,
            "handoff": None,
            "ask_request": None,
        }

        async def _run() -> None:
            try:
                final = cast(
                    AgentState,
                    await self._graph.ainvoke(
                        initial,
                        config={"recursion_limit": 2 * self._max_rounds + 2},
                    ),
                )
                self.last_usage = final.get("usage")
                self.last_messages = final.get("messages", [])
                self.error = final.get("error")
                self.last_handoff = final.get("handoff")
                self.last_ask_request = final.get("ask_request")
                # 正常收尾时 rounds ≤ max_rounds；进入强制收尾轮（rounds >=
                # max_tool_rounds 的 llm_call）后 rounds 会超过上限，据此判定触顶。
                self.rounds_exhausted = (final.get("rounds") or 0) > self._max_rounds
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                await queue.put(ChatChunk(type="error", content=f"运行时异常: {e}"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()
