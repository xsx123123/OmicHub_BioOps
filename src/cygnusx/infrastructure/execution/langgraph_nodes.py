"""LangGraph 图节点：llm_call / tool_exec / 条件路由

对应 legacy 手写 ReAct 循环（ChatService.stream_agent_chat）的图化版本：

- llm_call:  调 provider_manager.chat_stream 流式打模型，text/reasoning chunk
             经注入的事件回调实时透出；收集本轮正文与 tool_calls，append
             assistant 消息（含 tool_calls）。
- tool_exec: 逐个执行 tool_call（注入的 async tool_executor），执行前后各透出
             对齐 legacy 的 tool_call / tool_result ChatChunk；结果 JSON 超
             4000 字符截断后以 role:tool 消息 append。

设计原则：
    - 节点为纯函数（state, deps）→ 增量 state，副作用全部经 deps 注入
    - 异常安全：节点捕获异常并透出 error chunk，设置 state["error"] 由路由收尾
    - 路由函数返回字符串 key，由运行时映射到 END/节点，节点模块不依赖 langgraph
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cygnusx.application.services.execution_events import execution_chunk
from cygnusx.core.telemetry import get_tracer
from cygnusx.domain.execution.agent_state import AgentState
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    ChatChunk,
    merge_token_usage,
    provider_manager,
)

# 与 legacy 循环一致：tool 结果回灌 LLM 前按 4000 字符截断
TOOL_RESULT_MAX_CHARS = 4000
# 技能 L2 正文（use_skill）允许更长回灌，与 legacy 循环的 llm_limit 保持一致
SKILL_TOOL_MAX_CHARS = 24000

ChatStreamFn = Callable[..., AsyncIterator[ChatChunk]]
ToolExecutorFn = Callable[[str, dict[str, Any], str], Awaitable[dict[str, Any]]]
EventEmitter = Callable[[ChatChunk], Awaitable[None]]
ChannelResolver = Callable[[str], str | None]


@dataclass
class NodeDeps:
    """节点依赖容器 — 由 LangGraphRuntimeService 构造注入，便于测试 mock"""

    model_config: Any
    system_prompt: str | None = None
    temperature: float = 0.3
    max_tokens: int = 65536
    tools: list[dict[str, Any]] | None = None
    deep_thinking: bool = False
    max_tool_rounds: int | None = None
    tool_executor: ToolExecutorFn | None = None
    channel_resolver: ChannelResolver | None = None
    chat_stream: ChatStreamFn | None = None
    emit: EventEmitter | None = None
    emit_execution_events: bool = False
    session_id: str = ""
    run_id: str = ""
    agent_id: str = ""
    execution_path: str = "chat_langgraph"

    async def emit_chunk(self, chunk: ChatChunk) -> None:
        if self.emit is not None:
            await self.emit(chunk)

    async def emit_execution(
        self,
        event_type: str,
        *,
        round_number: int,
        content: str = "",
        **payload: Any,
    ) -> None:
        if not self.emit_execution_events:
            return
        await self.emit_chunk(
            execution_chunk(
                event_type,
                session_id=self.session_id,
                run_id=self.run_id,
                agent_id=self.agent_id,
                round_number=round_number,
                execution_path=self.execution_path,
                content=content,
                **payload,
            )
        )


async def llm_call_node(state: AgentState, deps: NodeDeps) -> dict[str, Any]:
    """调用 LLM（流式），append assistant 消息（可能含 tool_calls）"""
    messages = state.get("messages", [])
    usage = state.get("usage")
    rounds = state.get("rounds", 0)
    stream = deps.chat_stream or provider_manager.chat_stream
    force_final_response = (
        deps.max_tool_rounds is not None and rounds >= deps.max_tool_rounds
    )
    # agent_turn_started 由外层 Runtime 统一发送（对齐 legacy 每轮一次），
    # 图内不再重复发送。
    system_prompt = deps.system_prompt
    tools = deps.tools or None
    if force_final_response:
        tools = None
        system_prompt = (
            f"{system_prompt or ''}\n\n"
            "工具调用额度已用尽。现在必须基于已有工具结果给出最终答复；"
            "不要继续调用工具，也不要只描述下一步。"
        )

    round_text = ""
    round_reasoning = ""
    tool_calls: list[dict[str, Any]] = []
    try:
        async for chunk in stream(
            config=deps.model_config,
            messages=messages,
            system_prompt=system_prompt,
            temperature=deps.temperature,
            max_tokens=deps.max_tokens,
            tools=tools,
            deep_thinking=deps.deep_thinking,
        ):
            if chunk.type == "text":
                if chunk.metadata.get("is_reasoning"):
                    await deps.emit_execution(
                        "agent_reasoning_delta",
                        round_number=rounds + 1,
                        content=chunk.content,
                        visibility="debug",
                    )
                # 推理过程（is_reasoning）透传但不并入最终正文，与 legacy 一致
                await deps.emit_chunk(chunk)
                if chunk.metadata.get("is_reasoning"):
                    round_reasoning += chunk.content
                else:
                    round_text += chunk.content
            elif chunk.type == "tool_calls":
                tool_calls = chunk.metadata.get("tool_calls", [])
            elif chunk.type == "error":
                await deps.emit_chunk(chunk)
                return {"rounds": rounds + 1, "usage": usage, "error": chunk.content}
            elif chunk.type == "done":
                usage = merge_token_usage(usage, chunk.metadata.get("usage"))
    except Exception as e:  # noqa: BLE001
        await deps.emit_chunk(ChatChunk(type="error", content=f"模型调用失败: {e}"))
        return {"rounds": rounds + 1, "usage": usage, "error": str(e)}

    if force_final_response:
        tool_calls = []
        if not round_text:
            round_text = "已完成可执行的工具步骤，请根据上方工具结果继续处理。"
            await deps.emit_chunk(ChatChunk(type="text", content=round_text))

    # Code Cell 不占 tool 轮次预算（§3.3.2）：上一轮工具批次全部为代码执行类
    # 工具时，本轮 llm_call 不递增轮次（force_final_response 判定与事件
    # round_number 仍以递增前的 rounds 为准）。
    next_rounds = rounds if state.get("code_cell_only_round") else rounds + 1

    assistant: dict[str, Any] = {"role": "assistant", "content": round_text}
    if round_reasoning:
        # DeepSeek tool calling 要求工具结果回灌时保留上一轮推理内容。
        assistant["reasoning_content"] = round_reasoning
    if tool_calls:
        assistant["tool_calls"] = tool_calls
    return {"messages": [assistant], "rounds": next_rounds, "usage": usage, "error": None}


async def tool_exec_node(state: AgentState, deps: NodeDeps) -> dict[str, Any]:
    """逐个执行最后一条 assistant 消息中的 tool_calls，append role:tool 结果"""
    messages = state.get("messages", [])
    last = messages[-1] if messages else {}
    tool_calls: list[dict[str, Any]] = last.get("tool_calls") or []
    if not tool_calls or deps.tool_executor is None:
        return {"error": "tool_exec 节点缺少 tool_calls 或执行器"}

    new_messages: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = tc.get("function", {}) or {}
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", "")
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
        tool_call_id = tc.get("id", "")
        channel = deps.channel_resolver(tool_name) if deps.channel_resolver else None

        await deps.emit_chunk(
            ChatChunk(
                type="tool_call",
                metadata={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "arguments": args,
                    "mcp_server": channel,
                },
            )
        )
        await deps.emit_execution(
            "agent_tool_call",
            round_number=state.get("rounds", 0) + 1,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=args,
            phase="model_requested",
        )
        await deps.emit_execution(
            "agent_tool_started",
            round_number=state.get("rounds", 0) + 1,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

        tracer = get_tracer("cygnusx.chat")
        with tracer.start_as_current_span(
            "agent.tool_dispatch",
            attributes={"tool.name": tool_name, "tool.call_id": tool_call_id},
        ) as span:
            try:
                result = await deps.tool_executor(tool_name, args, tool_call_id)
            except Exception as e:  # noqa: BLE001
                span.record_exception(e)
                await deps.emit_chunk(
                    ChatChunk(type="error", content=f"工具 {tool_name} 执行失败: {e}")
                )
                return {"messages": new_messages, "error": str(e)}

        # 双通道：llm_payload 给 LLM，ui_payload 给前端（对齐 legacy 拆分逻辑）
        tool_output = result.get("result") if isinstance(result, dict) else result
        if isinstance(tool_output, dict) and (
            "llm_payload" in tool_output or "ui_payload" in tool_output
        ):
            ui_payload = tool_output.get("ui_payload")
            llm_result = tool_output.get("llm_payload", tool_output)
        else:
            ui_payload = None
            llm_result = tool_output if tool_output is not None else result
        if not isinstance(llm_result, dict):
            llm_result = {"result": llm_result}

        await deps.emit_chunk(
            ChatChunk(
                type="tool_result",
                metadata={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "mcp_server": channel,
                    "success": bool(result.get("success"))
                    if isinstance(result, dict)
                    else True,
                    "result": llm_result,
                    "ui_payload": ui_payload,
                    "reliability": result.get("reliability")
                    if isinstance(result, dict)
                    else None,
                },
            )
        )
        await deps.emit_execution(
            "agent_tool_result",
            round_number=state.get("rounds", 0) + 1,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            success=bool(result.get("success")) if isinstance(result, dict) else True,
        )

        llm_content = json.dumps(llm_result, ensure_ascii=False, default=str)
        from cygnusx.domain.skill.services import SKILL_TOOL_NAMES

        limit = SKILL_TOOL_MAX_CHARS if tool_name in SKILL_TOOL_NAMES else TOOL_RESULT_MAX_CHARS
        if len(llm_content) > limit:
            llm_content = llm_content[:limit]
        new_messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": llm_content}
        )
        from cygnusx.application.services.agent_handoff_service import (
            extract_handoff_directive,
        )

        directive = extract_handoff_directive(result)
        if directive is not None and bool(result.get("success", False)):
            return {"messages": new_messages, "handoff": directive, "error": None}
        # ask_user 澄清：对齐 legacy 的 stop_after_tools —— 结束当前图，
        # 由 ChatService 产出 ask_request 事件并收尾本轮，等用户下条消息回答。
        if (
            tool_name == "ask_user"
            and isinstance(result, dict)
            and bool(result.get("success", False))
        ):
            # 对齐 legacy chat_service.py:5405-5414：ask 轮同样发出轮级
            # agent_context_reinjected（handoff 轮不发，legacy 5386-5403 提前 continue）。
            await deps.emit_execution(
                "agent_context_reinjected",
                round_number=state.get("rounds", 0) + 1,
                tool_call_count=len(tool_calls),
                phase="after_tool_result",
            )
            return {
                "messages": new_messages,
                "ask_request": {"tool_call_id": tool_call_id, "args": args},
                "error": None,
            }
        # 显式 Finalize 动作（submit_output，§3.3.1）：模型主动提交最终答复并
        # 结束本轮。工具结果照常回灌（保持上下文完整），图经 state["finalize"]
        # 路由到 end，由外层 Runtime 把 output 作为最终正文收尾。
        if (
            tool_name == "submit_output"
            and isinstance(result, dict)
            and bool(result.get("success", False))
        ):
            await deps.emit_execution(
                "agent_context_reinjected",
                round_number=state.get("rounds", 0) + 1,
                tool_call_count=len(tool_calls),
                phase="after_tool_result",
            )
            return {
                "messages": new_messages,
                "finalize": {
                    "tool_call_id": tool_call_id,
                    "output": str(args.get("output") or ""),
                },
                "error": None,
            }
    # 轮级回灌事件（对齐 legacy 每轮一次，而非每工具一次）：本轮全部工具结果
    # 已写入 role:tool 消息，下一轮模型调用具备继续条件。
    await deps.emit_execution(
        "agent_context_reinjected",
        round_number=state.get("rounds", 0) + 1,
        tool_call_count=len(tool_calls),
        phase="after_tool_result",
    )
    await deps.emit_execution(
        "agent_turn_continued",
        round_number=state.get("rounds", 0) + 2,
        reason="tool_results_reinjected",
        tool_call_count=len(tool_calls),
    )
    # Code Cell 轮次豁免标记（§3.3.2）：本批 tool_calls 全部为代码执行类工具时，
    # 下一轮 llm_call 不递增轮次预算。
    from cygnusx.application.services.chat.utils import CODE_EXECUTION_TOOL_NAMES

    code_cell_only = bool(tool_calls) and all(
        (tc.get("function", {}) or {}).get("name", "") in CODE_EXECUTION_TOOL_NAMES
        for tc in tool_calls
    )
    return {"messages": new_messages, "error": None, "code_cell_only_round": code_cell_only}


def route_after_llm(state: AgentState) -> str:
    """LLM 调用后路由：有 tool_calls → tool_exec；出错或无工具调用 → end"""
    if state.get("error"):
        return "end"
    messages = state.get("messages", [])
    last = messages[-1] if messages else {}
    if last.get("tool_calls"):
        return "tool_exec"
    return "end"


def route_after_tool(state: AgentState, max_rounds: int) -> str:
    """工具执行后路由：达到上限时进入无工具的最终总结轮。"""
    if state.get("error"):
        return "end"
    if state.get("handoff"):
        return "end"
    if state.get("ask_request"):
        return "end"
    if state.get("finalize"):
        return "end"
    return "llm_call"
