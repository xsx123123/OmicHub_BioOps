"""
LangGraph 节点函数定义
=======================
OmicHub Agent 调度逻辑转换为 LangGraph StateGraph 节点。

节点列表:
    - assemble:     组装上下文（从 AgentService 复用）
    - llm_call:     调用 LLM（从 ProviderManager 复用）
    - tool_exec:    执行 MCP 工具（从 MCPClient 复用）
    - hitl_check:   检查是否需要 HITL 中断
    - task_builder: 构建分析任务（调用 GenericFlowBuilder）

设计原则:
    - 纯函数: 输入 AgentState → 输出 AgentState（无副作用）
    - 异常安全: 捕获异常，设置 state.error，不抛错
    - 可观测: 每个节点记录 latency 和 token 消耗
"""

from __future__ import annotations

import asyncio
import time
import json
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from omichub.domain.execution.agent_state import (
    AgentState,
    ExecutionMetadata,
    HITLPayload,
    HITLStatus,
    TaskContext,
    ToolCallRecord,
)
from omichub.domain.execution.hitl_models import HITLType


# ──────────────────────────────
# 工具与依赖注入（运行时传入）
# ──────────────────────────────

class NodeDeps:
    """
    节点依赖容器 —— 在 LangGraphRuntimeService 中创建并注入。
    避免全局单例，支持测试 mock。
    """

    def __init__(
        self,
        agent_service: Any,           # AgentService
        provider_manager: Any,        # ProviderManager
        mcp_client: Any,              # MCPClient
        task_service: Any,            # TaskService
        chat_service: Any,            # ChatService（用于消息持久化）
    ):
        self.agent_service = agent_service
        self.provider_manager = provider_manager
        self.mcp_client = mcp_client
        self.task_service = task_service
        self.chat_service = chat_service


# ═══════════════════════════════════
# 节点 1: assemble —— 组装上下文
# ═══════════════════════════════════

async def assemble_node(state: AgentState, deps: NodeDeps) -> AgentState:
    """
    组装 Agent 上下文 —— 复用 AgentService.assemble_context 逻辑。

    输入: 初始 AgentState（含用户消息、agent_id）
    输出: 填充 system_prompt、tools、mcp_servers、model_config 的状态
    """
    start = time.time()

    try:
        agent_id = state.metadata.agent_id
        if not agent_id:
            return state.set_error("缺少 agent_id，无法组装上下文")

        # 调用现有 AgentService
        agent_context = await deps.agent_service.assemble_context(agent_id)

        # 填充状态
        state.system_prompt = agent_context.get("system_prompt", "")
        state.tools = agent_context.get("tools", [])
        state.mcp_servers = agent_context.get("mcp_servers", [])
        state.model_config_dict = agent_context.get("model_config")

        # 如果没有 SystemMessage，添加
        has_system = any(isinstance(m, SystemMessage) for m in state.messages)
        if not has_system and state.system_prompt:
            state.messages.insert(0, SystemMessage(content=state.system_prompt))

        # 记录元数据
        state.metadata.last_activity = time.time()

    except Exception as e:
        state.set_error(f"assemble 节点异常: {str(e)}")

    return state


# ═══════════════════════════════════
# 节点 2: llm_call —— 调用 LLM
# ═══════════════════════════════════

async def llm_call_node(state: AgentState, deps: NodeDeps) -> AgentState:
    """
    调用 LLM —— 复用 ProviderManager.chat_stream 逻辑。

    输入: 含 messages + tools + model_config 的状态
    输出: 添加 AIMessage（可能含 tool_calls）的状态
    """
    start = time.time()

    try:
        if not state.model_config_dict:
            return state.set_error("缺少 model_config，无法调用 LLM")

        # 构建 LLM 请求
        messages_for_llm = [
            {"role": _msg_to_role(m), "content": m.content}
            for m in state.messages
        ]

        # 调用 ProviderManager（非流式，LangGraph 内部处理流式）
        response = await deps.provider_manager.chat(
            model_config=state.model_config_dict,
            messages=messages_for_llm,
            tools=state.tools if state.tools else None,
            temperature=0.3,
        )

        # 解析响应
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])
        usage = response.get("usage", {})

        # 创建 AIMessage
        additional_kwargs = {}
        if tool_calls:
            additional_kwargs["tool_calls"] = tool_calls

        ai_message = AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
        )
        state.add_message(ai_message)

        # 更新 Token 消耗
        state.update_tokens(
            prompt=usage.get("prompt_tokens", 0),
            completion=usage.get("completion_tokens", 0),
        )

        state.metadata.last_activity = time.time()

    except Exception as e:
        state.set_error(f"llm_call 节点异常: {str(e)}")

    return state


# ═══════════════════════════════════
# 节点 3: tool_exec —— 执行 MCP 工具
# ═══════════════════════════════════

async def tool_exec_node(state: AgentState, deps: NodeDeps) -> AgentState:
    """
    执行 MCP 工具 —— 复用 MCPClient.call_tool 逻辑。

    输入: 最后一条 AIMessage 含 tool_calls
    输出: 添加 ToolMessage（工具执行结果）的状态
    """
    start = time.time()

    try:
        last_msg = state.last_message
        if not isinstance(last_msg, AIMessage):
            return state.set_error("最后一条消息不是 AIMessage，无法执行工具")

        tool_calls = last_msg.additional_kwargs.get("tool_calls", [])
        if not tool_calls:
            return state.set_error("AIMessage 中不含 tool_calls")

        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name", "")
            tool_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
            tool_call_id = tc.get("id", "")

            tool_start = time.time()
            success = True
            output = ""
            error = None

            try:
                # 调用 MCPClient
                result = await deps.mcp_client.call_tool(tool_name, tool_args)
                output = json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result

            except Exception as e:
                success = False
                error = str(e)
                output = f"工具执行失败: {error}"

            # 记录工具调用
            record = ToolCallRecord(
                tool_name=tool_name,
                tool_input=tool_args,
                tool_output=output if success else None,
                success=success,
                latency_ms=(time.time() - tool_start) * 1000,
                error=error,
            )
            state.add_tool_call(record)

            # 添加 ToolMessage
            tool_msg = ToolMessage(
                content=output,
                tool_call_id=tool_call_id,
                name=tool_name,
            )
            state.add_message(tool_msg)

        state.metadata.last_activity = time.time()

    except Exception as e:
        state.set_error(f"tool_exec 节点异常: {str(e)}")

    return state


# ═══════════════════════════════════
# 节点 4: hitl_check —— HITL 中断检查
# ═══════════════════════════════════

async def hitl_check_node(state: AgentState, deps: NodeDeps) -> AgentState:
    """
    检查是否需要 HITL 人工确认。

    中断点:
        1. param_confirm: AI 推荐分析参数后
        2. task_submit: 参数确认后、任务提交前
        3. result_review: 分析完成后

    输入: 含 task_context 的状态
    输出: 可能触发 HITL 中断的状态
    """
    try:
        # 只有在有 task_context 时才检查 HITL
        if not state.task_context:
            return state

        tc = state.task_context

        # 中断点 1: 参数确认
        if tc.recommended_params and not tc.param_confirmed:
            payload = HITLPayload(
                interrupt_for="param_confirm",
                title="确认分析参数",
                description="AI 已为您推荐以下分析参数，请确认或修改：",
                payload={
                    "flow_id": tc.flow_id,
                    "flow_name": tc.flow_name,
                    "recommended_params": tc.recommended_params,
                    "samples": tc.samples,
                },
                timeout_seconds=600,
            )
            state.hitl_interrupt(payload)
            return state

        # 中断点 2: 任务提交确认
        if tc.param_confirmed and tc.task_id is None:
            payload = HITLPayload(
                interrupt_for="task_submit",
                title="提交分析任务",
                description=f"即将提交 {tc.flow_name} 分析任务，确认继续？",
                payload={
                    "flow_id": tc.flow_id,
                    "parameters": tc.parameters,
                    "sample_count": len(tc.samples),
                },
                timeout_seconds=300,
            )
            state.hitl_interrupt(payload)
            return state

        # 中断点 3: 结果审核（由 task_status 变化触发，在 hitl_service 中处理）
        # 这里不处理，由外部事件触发

    except Exception as e:
        state.set_error(f"hitl_check 节点异常: {str(e)}")

    return state


# ═══════════════════════════════════
# 节点 5: task_builder —— 构建分析任务
# ═══════════════════════════════════

async def task_builder_node(state: AgentState, deps: NodeDeps) -> AgentState:
    """
    构建并提交分析任务 —— 调用 TaskService 和 GenericFlowBuilder。

    输入: 含 task_context（参数已确认）的状态
    输出: task_context.task_id 被填充
    """
    try:
        if not state.task_context:
            return state.set_error("缺少 task_context，无法构建任务")

        tc = state.task_context

        # 参数必须已确认
        if not tc.param_confirmed:
            return state.set_error("参数未确认，无法提交任务")

        # 已提交则跳过
        if tc.task_id:
            return state

        # 调用 TaskService 提交任务
        task_result = await deps.task_service.submit(
            user_id=state.metadata.user_id,
            flow_id=tc.flow_id,
            parameters=tc.parameters,
            samples=tc.samples,
            contrasts=tc.contrasts,
        )

        tc.task_id = task_result.get("task_id")
        tc.flow_name = task_result.get("flow_name", tc.flow_name)

        # 添加系统消息通知
        msg = f"任务已提交成功！任务ID: {tc.task_id}。您可以在任务面板查看进度。"
        state.add_message(AIMessage(content=msg))
        state.metadata.last_activity = time.time()

    except Exception as e:
        state.set_error(f"task_builder 节点异常: {str(e)}")

    return state


# ═══════════════════════════════════
# 条件边函数
# ═══════════════════════════════════

async def route_after_llm(state: AgentState, deps: NodeDeps) -> str:
    """
    LLM 调用后的条件路由:
        - 有 tool_calls → "tool_exec"
        - 已完成 / 出错 → "__end__"
        - 正常对话 → "hitl_check"
    """
    # 错误检查
    if state.error:
        # 错误次数过多，结束
        if state.error_count >= 3:
            state.finish(f"执行过程中出现多次错误，已终止。最后错误: {state.error}")
            return "__end__"
        # 可重试错误，继续 LLM 调用
        state.clear_error()
        return "llm_call"

    # 完成检查
    if state.is_finished:
        return "__end__"

    # HITL 检查
    if state.hitl_pending:
        return "interrupt"

    # 有 tool_calls → 执行工具
    if state.has_tool_calls_in_last_message:
        # 检查轮次限制
        if state.metadata.round_count >= state.metadata.max_rounds:
            state.finish("已达到最大对话轮次限制，执行结束。")
            return "__end__"
        return "tool_exec"

    # 没有 tool_calls，检查是否需要 HITL
    return "hitl_check"


async def route_after_tool(state: AgentState, deps: NodeDeps) -> str:
    """
    工具执行后的条件路由:
        - 正常 → 回到 llm_call
        - HITL 触发 → interrupt
        - 错误过多 → __end__
    """
    if state.error and state.error_count >= 3:
        state.finish(f"工具执行多次失败: {state.error}")
        return "__end__"

    if state.hitl_pending:
        return "interrupt"

    # 回到 LLM 继续对话
    state.increment_round()
    return "llm_call"


async def route_after_hitl(state: AgentState, deps: NodeDeps) -> str:
    """
    HITL 检查后的条件路由:
        - HITL 触发 → interrupt
        - 有 task_context 且参数已确认 → task_builder
        - 否则 → llm_call
    """
    if state.hitl_pending:
        return "interrupt"

    # 检查是否需要构建任务
    if state.task_context and state.task_context.param_confirmed and not state.task_context.task_id:
        return "task_builder"

    return "llm_call"


# ═══════════════════════════════════
# 辅助函数
# ═══════════════════════════════════

def _msg_to_role(msg) -> str:
    """将 LangChain Message 转换为 OpenAI 角色格式"""
    if isinstance(msg, HumanMessage):
        return "user"
    elif isinstance(msg, AIMessage):
        return "assistant"
    elif isinstance(msg, SystemMessage):
        return "system"
    elif isinstance(msg, ToolMessage):
        return "tool"
    return "user"
