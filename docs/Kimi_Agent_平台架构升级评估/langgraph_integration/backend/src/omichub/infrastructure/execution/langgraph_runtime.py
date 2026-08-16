"""
LangGraphRuntimeService
========================
LangGraph 运行时核心服务 —— 构建 StateGraph、管理线程、处理事件流。

职责:
    - 构建 StateGraph（节点 + 边）
    - 管理线程生命周期（创建 / 恢复 / 取消）
    - 执行事件流转换（LangGraph 事件 → OmicHub SSE 事件）
    - 并发控制（Semaphore 限制同时运行线程数）

设计:
    - 单例模式（由 lifespan 创建，注入到 Executor 和 API）
    - 异步生成器 yield 事件（SSE 流式推送）
    - 线程级取消（asyncio.Task.cancel）
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from omichub.domain.execution.agent_state import AgentState, HITLStatus
from omichub.infrastructure.execution.langgraph_nodes import (
    NodeDeps,
    assemble_node,
    hitl_check_node,
    llm_call_node,
    route_after_hitl,
    route_after_llm,
    route_after_tool,
    task_builder_node,
    tool_exec_node,
)
from omichub.infrastructure.checkpoint.postgres_checkpoint import OmicHubCheckpointSaver


# ──────────────────────────────
# SSE 事件模型（兼容前端现有格式）
# ──────────────────────────────

class SSEEvent:
    """SSE 事件 —— 兼容 OmicHub 前端现有 useAgentChatStream.ts"""

    def __init__(self, event_type: str, data: Dict[str, Any]):
        self.event_type = event_type
        self.data = data

    def to_sse_string(self) -> str:
        """转换为 SSE 格式字符串"""
        return f"event: {self.event_type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"

    @classmethod
    def text(cls, content: str, thread_id: str = "") -> SSEEvent:
        """文本块事件（打字机效果）"""
        return cls("text", {"content": content, "thread_id": thread_id})

    @classmethod
    def tool_call(cls, tool_name: str, tool_input: Dict, thread_id: str = "") -> SSEEvent:
        """工具调用事件"""
        return cls("tool_call", {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "thread_id": thread_id,
        })

    @classmethod
    def tool_result(cls, tool_name: str, result: str, success: bool, thread_id: str = "") -> SSEEvent:
        """工具结果事件"""
        return cls("tool_result", {
            "tool_name": tool_name,
            "result": result,
            "success": success,
            "thread_id": thread_id,
        })

    @classmethod
    def hitl_request(cls, payload: Dict[str, Any], thread_id: str = "") -> SSEEvent:
        """HITL 中断请求事件（前端收到后渲染确认弹窗）"""
        return cls("hitl_request", {
            "payload": payload,
            "thread_id": thread_id,
        })

    @classmethod
    def hitl_resumed(cls, action: str, thread_id: str = "") -> SSEEvent:
        """HITL 恢复事件"""
        return cls("hitl_resumed", {
            "action": action,
            "thread_id": thread_id,
        })

    @classmethod
    def done(cls, response: str, thread_id: str = "", metadata: Optional[Dict] = None) -> SSEEvent:
        """完成事件"""
        data = {"content": response, "thread_id": thread_id}
        if metadata:
            data["metadata"] = metadata
        return cls("done", data)

    @classmethod
    def error(cls, message: str, thread_id: str = "") -> SSEEvent:
        """错误事件"""
        return cls("error", {"message": message, "thread_id": thread_id})

    @classmethod
    def status(cls, phase: str, detail: str = "", thread_id: str = "") -> SSEEvent:
        """状态更新事件"""
        return cls("status", {"phase": phase, "detail": detail, "thread_id": thread_id})


# ──────────────────────────────
# 运行时服务
# ──────────────────────────────

class LangGraphRuntimeService:
    """
    LangGraph 运行时服务 —— 核心编排器
    """

    def __init__(
        self,
        node_deps: NodeDeps,
        checkpoint_saver: Optional[OmicHubCheckpointSaver] = None,
        max_concurrent_threads: int = 50,
    ):
        self._deps = node_deps
        self._checkpoint = checkpoint_saver
        self._semaphore = asyncio.Semaphore(max_concurrent_threads)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._graph: Optional[CompiledStateGraph] = None

    # ── 生命周期 ──

    async def initialize(self) -> None:
        """初始化 —— 构建 StateGraph"""
        self._graph = self._build_graph()

    async def shutdown(self) -> None:
        """关闭 —— 取消所有运行中任务"""
        for task in self._running_tasks.values():
            task.cancel()
        self._running_tasks.clear()

    # ── 核心执行 ──

    async def stream(
        self,
        initial_state: AgentState,
        thread_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        执行 Agent 流程，异步生成事件流。

        Args:
            initial_state: 初始 AgentState
            thread_id: 可选的 thread_id（恢复已有会话）

        Yields:
            事件字典: {type: str, data: dict, state: AgentState}
        """
        async with self._semaphore:
            tid = thread_id or initial_state.metadata.thread_id or f"omh_{uuid.uuid4().hex[:16]}"
            initial_state.metadata.thread_id = tid

            config = {
                "configurable": {
                    "thread_id": tid,
                    "checkpoint_ns": "",
                    "checkpoint_id": None,
                }
            }

            try:
                # 构建或获取图
                if not self._graph:
                    self._graph = self._build_graph()

                # 绑定 checkpoint saver
                graph = self._graph
                if self._checkpoint:
                    graph = graph.with_checkpoint_saver(self._checkpoint)

                yield {
                    "type": "status",
                    "data": {"phase": "started", "thread_id": tid},
                    "state": initial_state,
                }

                # 执行图
                async for event in graph.astream(
                    initial_state.model_dump(),
                    config=config,
                    stream_mode="updates",
                ):
                    # 解析 LangGraph 事件
                    for node_name, node_output in event.items():
                        if node_name == "__interrupt__":
                            # HITL 中断
                            state = AgentState.model_validate(node_output)
                            if state.hitl_pending and state.hitl_payload:
                                yield {
                                    "type": "hitl_request",
                                    "data": {
                                        "payload": state.hitl_payload.model_dump(),
                                        "thread_id": tid,
                                    },
                                    "state": state,
                                }
                            continue

                        # 正常节点输出
                        state = AgentState.model_validate(node_output)

                        # 根据节点类型生成对应事件
                        if node_name == "llm_call":
                            last_msg = state.last_message
                            if last_msg and hasattr(last_msg, "content"):
                                yield {
                                    "type": "text",
                                    "data": {"content": last_msg.content, "thread_id": tid},
                                    "state": state,
                                }

                        elif node_name == "tool_exec":
                            for tc in state.tool_calls[-3:]:  # 最近3个工具调用
                                yield {
                                    "type": "tool_result",
                                    "data": {
                                        "tool_name": tc.tool_name,
                                        "result": tc.tool_output or tc.error,
                                        "success": tc.success,
                                        "latency_ms": tc.latency_ms,
                                        "thread_id": tid,
                                    },
                                    "state": state,
                                }

                        elif node_name == "hitl_check" and state.hitl_pending:
                            if state.hitl_payload:
                                yield {
                                    "type": "hitl_request",
                                    "data": {
                                        "payload": state.hitl_payload.model_dump(),
                                        "thread_id": tid,
                                    },
                                    "state": state,
                                }

                        elif node_name == "task_builder":
                            if state.task_context and state.task_context.task_id:
                                yield {
                                    "type": "status",
                                    "data": {
                                        "phase": "task_submitted",
                                        "task_id": state.task_context.task_id,
                                        "thread_id": tid,
                                    },
                                    "state": state,
                                }

                        # 完成检查
                        if state.is_finished:
                            yield {
                                "type": "done",
                                "data": {
                                    "content": state.final_response or "执行完成",
                                    "thread_id": tid,
                                    "metadata": {
                                        "round_count": state.metadata.round_count,
                                        "total_tokens": state.metadata.total_tokens,
                                        "tool_calls_count": len(state.tool_calls),
                                    },
                                },
                                "state": state,
                            }
                            return

                # 流结束但没有 is_finished 标记
                yield {
                    "type": "done",
                    "data": {"content": "会话结束", "thread_id": tid},
                    "state": initial_state,
                }

            except asyncio.CancelledError:
                yield {
                    "type": "error",
                    "data": {"message": "执行已取消", "thread_id": tid},
                    "state": initial_state,
                }

            except Exception as e:
                yield {
                    "type": "error",
                    "data": {"message": f"运行时异常: {str(e)}", "thread_id": tid},
                    "state": initial_state,
                }

    async def invoke(
        self,
        initial_state: AgentState,
        thread_id: Optional[str] = None,
    ) -> AgentState:
        """
        同步执行（非流式），返回最终状态。
        用于后台任务和测试。
        """
        final_state = initial_state
        async for event in self.stream(initial_state, thread_id):
            if event["type"] in ("done", "error"):
                final_state = event.get("state", initial_state)
                break
        return final_state

    # ── HITL 恢复 ──

    async def resume_hitl(
        self,
        thread_id: str,
        human_input: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        恢复 HITL 中断的执行。

        通过 Command(resume=...) 机制恢复中断的图。
        """
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        try:
            if not self._graph:
                self._graph = self._build_graph()

            graph = self._graph
            if self._checkpoint:
                graph = graph.with_checkpoint_saver(self._checkpoint)

            # 使用 Command 恢复
            async for event in graph.astream(
                Command(resume=human_input),
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in event.items():
                    state = AgentState.model_validate(node_output)

                    if node_name == "llm_call" and state.last_message:
                        yield {
                            "type": "text",
                            "data": {"content": state.last_message.content, "thread_id": thread_id},
                            "state": state,
                        }
                    elif state.is_finished:
                        yield {
                            "type": "done",
                            "data": {
                                "content": state.final_response or "执行完成",
                                "thread_id": thread_id,
                            },
                            "state": state,
                        }
                        return

        except Exception as e:
            yield {
                "type": "error",
                "data": {"message": f"HITL 恢复异常: {str(e)}", "thread_id": thread_id},
            }

    # ── 任务管理 ──

    async def cancel(self, thread_id: str) -> bool:
        """取消运行中的任务"""
        task = self._running_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def get_status(self, thread_id: str) -> Dict[str, Any]:
        """获取线程状态"""
        if self._checkpoint:
            status = await self._checkpoint.get_thread_status(thread_id)
            if status:
                return {
                    "thread_id": thread_id,
                    "status": status.get("status", "unknown"),
                    "user_id": status.get("user_id"),
                    "session_id": status.get("session_id"),
                    "updated_at": status.get("updated_at"),
                }
        return {"thread_id": thread_id, "status": "unknown"}

    # ── 内部: 构建 StateGraph ──

    def _build_graph(self) -> CompiledStateGraph:
        """
        构建 LangGraph StateGraph

        图结构:
            __start__ → assemble → llm_call → [条件边]
            [有tool_calls] → tool_exec → [条件边] → llm_call
            [无tool_calls] → hitl_check → [条件边]
            [HITL触发] → interrupt (等待恢复)
            [需构建任务] → task_builder → llm_call
            [完成] → __end__
        """
        builder = StateGraph(AgentState)

        # 添加节点
        builder.add_node("assemble", self._wrap_node(assemble_node))
        builder.add_node("llm_call", self._wrap_node(llm_call_node))
        builder.add_node("tool_exec", self._wrap_node(tool_exec_node))
        builder.add_node("hitl_check", self._wrap_node(hitl_check_node))
        builder.add_node("task_builder", self._wrap_node(task_builder_node))

        # 边: __start__ → assemble
        builder.set_entry_point("assemble")

        # 边: assemble → llm_call
        builder.add_edge("assemble", "llm_call")

        # 条件边: llm_call → ?
        builder.add_conditional_edges(
            "llm_call",
            self._wrap_router(route_after_llm),
            {
                "tool_exec": "tool_exec",
                "hitl_check": "hitl_check",
                "llm_call": "llm_call",
                "interrupt": END,  # HITL 中断，图暂停
                "__end__": END,
            },
        )

        # 条件边: tool_exec → ?
        builder.add_conditional_edges(
            "tool_exec",
            self._wrap_router(route_after_tool),
            {
                "llm_call": "llm_call",
                "interrupt": END,
                "__end__": END,
            },
        )

        # 条件边: hitl_check → ?
        builder.add_conditional_edges(
            "hitl_check",
            self._wrap_router(route_after_hitl),
            {
                "task_builder": "task_builder",
                "llm_call": "llm_call",
                "interrupt": END,
            },
        )

        # 边: task_builder → llm_call
        builder.add_edge("task_builder", "llm_call")

        return builder.compile(
            checkpointer=self._checkpoint,
            interrupt_after=["hitl_check"],  # HITL 检查后可能中断
        )

    def _wrap_node(self, node_func):
        """包装节点函数，注入 deps"""
        async def wrapper(state_dict: Dict[str, Any]) -> Dict[str, Any]:
            state = AgentState.model_validate(state_dict)
            result = await node_func(state, self._deps)
            return result.model_dump()
        return wrapper

    def _wrap_router(self, router_func):
        """包装路由函数，注入 deps"""
        async def wrapper(state_dict: Dict[str, Any]) -> str:
            state = AgentState.model_validate(state_dict)
            return await router_func(state, self._deps)
        return wrapper
