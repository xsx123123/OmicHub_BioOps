"""LangGraph Agent Runtime。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from loguru import logger

from cygnusx.application.services.agent_handoff_service import HANDOFF_TOOL_NAME
from cygnusx.application.services.chat.configuration import (
    RESEARCH_TOOL_CHANNEL,
    RESEARCH_TOOL_NAMES,
)
from cygnusx.application.services.chat.next_step_suggestions import suggestions_metadata
from cygnusx.application.services.chat.runtimes.delegating_runtime import DelegatingAgentRuntime
from cygnusx.application.services.chat.utils import (
    _cap_tool_invocation_payload_detail,
    _code_cell_envelope_fields,
    _fanout_ask_request,
    _invocation_payload_hash,
    _max_persisted_cell_index,
    _normalize_ask_questions,
    _studio_risk_hint,
)
from cygnusx.application.services.chat_sandbox_tools import (
    CHAT_SANDBOX_TOOL_NAME,
    execute_chat_sandbox,
)
from cygnusx.application.services.network_request_tool import (
    NETWORK_REQUEST_TOOL_NAME,
    execute_network_request,
)
from cygnusx.application.services.execution_events import execution_chunk, execution_metadata
from cygnusx.application.services.mas_plan_adapter import MAS_PLAN_PREVIEW_TOOL_NAME
from cygnusx.application.services.parallel_subagent_service import PARALLEL_SUBAGENTS_TOOL_NAME
from cygnusx.application.services.studio_approval_service import (
    APPROVAL_TTL_SECONDS,
    always_allow_set,
    get_studio_approval_service,
    needs_approval,
    record_approval_audit,
)
from cygnusx.application.services.studio_tools import (
    SUBMIT_OUTPUT_TOOL_NAME,
    SUBMIT_OUTPUT_TOOL_SCHEMA,
)
from cygnusx.core.config import get_settings
from cygnusx.domain.skill.services import SKILL_TOOL_NAMES
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    ChatChunk,
    merge_token_usage,
    provider_manager,
)

_EmitFn = Callable[[ChatChunk], Awaitable[None]]


async def _gate_chat_sandbox_approval(
    *,
    emit: _EmitFn,
    user_id: str,
    session_id: str,
    tool_call_id: str,
    args: dict[str, Any],
    permission_mode: str | None,
    always_allow: set[str],
    auto_approve: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """chat_sandbox_execute 的 supervised 审批闸，语义逐点对齐 legacy 手写循环
    （chat_service.py 的 is_chat_sandbox_tool 分支）：

    - needs_approval 判定（supervised 模式 ∧ 拦截名单 ∧ 未 always_allow）；
    - StudioApprovalService.create 写 Redis pending 记录（TTL 300s）；
    - 经 emit 下发 approval_request（含 timeout_seconds），等待期间每 15s 发
      heartbeat（与 legacy 的 SSE 保活一致）；
    - 决议经 BLPOP 回来后下发 approval_resolved；edited 携 modified_args
      替换参数并按 approved 处理；approved + always 写入流内 always_allow；
    - timeout 经 record_approval_audit 落 audit_logs（method="EVENT"）；
    - 拒绝/超时返回 rejection 信封（success=False, rejected=True），由调用方
      作为工具结果回灌 LLM 与前端。

    返回 (生效参数, 拒绝信封)：通过时拒绝信封为 None。

    auto_approve=True（AI 助手页面）时不建审批记录、不下发事件，直接放行。
    """
    if auto_approve:
        return args, None
    if not needs_approval(permission_mode, CHAT_SANDBOX_TOOL_NAME, always_allow):
        return args, None
    approval_service = get_studio_approval_service()
    approval = await approval_service.create(
        user_id=user_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=CHAT_SANDBOX_TOOL_NAME,
        arguments=args,
        risk_hint=_studio_risk_hint(CHAT_SANDBOX_TOOL_NAME, args),
    )
    await emit(
        ChatChunk(
            type="approval_request",
            metadata={
                "approval_id": approval["approval_id"],
                "tool_call_id": tool_call_id,
                "tool_name": CHAT_SANDBOX_TOOL_NAME,
                "arguments": args,
                "risk_hint": approval["risk_hint"],
                "timeout_seconds": APPROVAL_TTL_SECONDS,
            },
        )
    )
    resolution_task = asyncio.create_task(
        approval_service.wait_resolution(approval["approval_id"])
    )
    try:
        while not resolution_task.done():
            await asyncio.wait({resolution_task}, timeout=15)
            if not resolution_task.done():
                await emit(ChatChunk(type="heartbeat"))
        resolution = resolution_task.result()
    finally:
        if not resolution_task.done():
            resolution_task.cancel()
    action = str(resolution.get("action") or "timeout")
    await emit(
        ChatChunk(
            type="approval_resolved",
            metadata={
                "approval_id": approval["approval_id"],
                "tool_call_id": tool_call_id,
                "action": action,
            },
        )
    )
    if action == "edited" and isinstance(resolution.get("modified_args"), dict):
        args = resolution["modified_args"]
        action = "approved"
    if action == "approved" and resolution.get("always"):
        always_allow.add(CHAT_SANDBOX_TOOL_NAME)
    if action == "timeout":
        await record_approval_audit(
            user_id=str(user_id),
            approval_id=approval["approval_id"],
            session_id=str(session_id),
            tool_name=CHAT_SANDBOX_TOOL_NAME,
            action="timeout",
            resolver="timeout",
            arguments=args,
            method="EVENT",
        )
    if action != "approved":
        reason = resolution.get("reason") or (
            "用户未响应（超时）" if action == "timeout" else "用户拒绝了该操作"
        )
        reject_payload = {"rejected": True, "error": reason}
        return args, {
            "success": False,
            "rejected": True,
            "result": {
                "llm_payload": reject_payload,
                "ui_payload": dict(reject_payload),
            },
        }
    return args, None


async def _gate_network_request_approval(
    *,
    emit: _EmitFn,
    user_id: str,
    session_id: str,
    tool_call_id: str,
    args: dict[str, Any],
    permission_mode: str | None,
    always_allow: set[str],
    auto_approve: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """网络访问使用与沙盒相同的 Redis/SSE 审批协议。

    auto_approve=True（AI 助手页面）时直接放行，不出审批卡。
    """
    if auto_approve:
        return args, None
    if not needs_approval(permission_mode, NETWORK_REQUEST_TOOL_NAME, always_allow):
        return args, None
    approval_service = get_studio_approval_service()
    approval = await approval_service.create(
        user_id=user_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=NETWORK_REQUEST_TOOL_NAME,
        arguments=args,
        risk_hint=_studio_risk_hint(NETWORK_REQUEST_TOOL_NAME, args),
    )
    await emit(ChatChunk(type="approval_request", metadata={
        "approval_id": approval["approval_id"], "tool_call_id": tool_call_id,
        "tool_name": NETWORK_REQUEST_TOOL_NAME, "arguments": args,
        "risk_hint": approval["risk_hint"], "timeout_seconds": APPROVAL_TTL_SECONDS,
    }))
    resolution_task = asyncio.create_task(approval_service.wait_resolution(approval["approval_id"]))
    try:
        while not resolution_task.done():
            await asyncio.wait({resolution_task}, timeout=15)
            if not resolution_task.done():
                await emit(ChatChunk(type="heartbeat"))
        resolution = resolution_task.result()
    finally:
        if not resolution_task.done():
            resolution_task.cancel()
    action = str(resolution.get("action") or "timeout")
    await emit(ChatChunk(type="approval_resolved", metadata={
        "approval_id": approval["approval_id"], "tool_call_id": tool_call_id, "action": action,
    }))
    if action == "edited" and isinstance(resolution.get("modified_args"), dict):
        args = resolution["modified_args"]
        action = "approved"
    if action == "approved" and resolution.get("always"):
        always_allow.add(NETWORK_REQUEST_TOOL_NAME)
    if action == "timeout":
        await record_approval_audit(
            user_id=str(user_id), approval_id=approval["approval_id"], session_id=str(session_id),
            tool_name=NETWORK_REQUEST_TOOL_NAME, action="timeout", resolver="timeout",
            arguments=args, method="EVENT",
        )
    if action != "approved":
        reason = resolution.get("reason") or ("用户未响应（超时）" if action == "timeout" else "用户拒绝了该网络请求")
        payload = {"success": False, "rejected": True, "result": {
            "llm_payload": {"rejected": True, "error": reason},
            "ui_payload": {"rejected": True, "error": reason},
        }}
        return args, payload
    return args, None


class LangGraphChatRuntime(DelegatingAgentRuntime):
    """LangGraph 请求的显式 Runtime 身份与通用 ReAct 流循环。"""

    async def _stream_agent_chat_langgraph(
        self,
        *,
        user_id: str,
        session_id: str,
        ai_message_id: str,
        model_config: Any,
        llm_messages: list[dict[str, Any]],
        system_prompt: str | None,
        tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        deep_thinking: bool,
        active_mcp_servers: list[Any],
        mcp_client: Any,
        tool_context: Any,
        skills: list[Any] | None = None,
        skill_pins: dict[str, int] | None = None,
        web_sources: list[dict[str, Any]] | None = None,
        handoff_handler: Any | None = None,
        extend_max_rounds: bool = False,
        auto_approve: bool = False,
    ) -> AsyncIterator[ChatChunk]:
        """LangGraph 引擎路径：状态图驱动 ReAct 循环，事件协议与手写循环一致

        tool_executor 复刻 legacy 非 Studio 工具路由：技能内部工具（use_skill /
        skill_resource）→ self._service._execute_skill_tool；ask_user → 澄清信封（图经
        state["ask_request"] 收尾，由本函数产出 ask_request 事件）；knowledge_search →
        self._service._knowledge_search_chat；MCP server 匹配 → MCPClient.call_tool；
        web_search → self._service._web_search；未挂载 → 报错信封。

        auto_approve=True（AI 助手页面）时两个审批闸（chat_sandbox_execute /
        network_request）直接跳过，操作即时执行；AI 工作台页面不传该标记，
        维持 supervised 逐次审批。
        """
        runtime_state: dict[str, Any] = {
            "model_config": model_config,
            "llm_messages": list(llm_messages),
            "system_prompt": system_prompt,
            "tools": list(tools),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "active_mcp_servers": list(active_mcp_servers),
            "tool_context": tool_context,
            "skills": list(skills or []),
            "skill_pins": skill_pins or {},
        }
        persisted_web_sources = web_sources if web_sources is not None else []
        # 审批闸上下文（对齐 legacy chat_service）：仅当会话显式携带
        # sandbox_meta.permissions.mode 时启用审批；always_allow 集合支持流内
        # always 批准动态补充，同流内后续调用直接放行。
        # auto_approve（AI 助手页面）为真时两个闸整体跳过，见 _gate_* 早返回。
        approval_session = await self._service.get_session(session_id, user_id)
        approval_sandbox_meta = (
            dict(approval_session.sandbox_meta or {}) if approval_session else {}
        )
        _permissions = approval_sandbox_meta.get("permissions")
        chat_permission_mode = (
            _permissions.get("mode") if isinstance(_permissions, dict) else None
        )
        chat_always_allow = always_allow_set(approval_sandbox_meta)
        # NodeDeps 每轮循环重建，emit 由 LangGraphRuntimeService.stream 在图执行前
        # 挂到 deps 上；经 holder 让工具执行器拿到当前轮的 emit 以透出审批事件。
        deps_holder: dict[str, Any] = {}

        async def _emit(chunk: ChatChunk) -> None:
            deps = deps_holder.get("deps")
            if deps is not None and deps.emit is not None:
                await deps.emit(chunk)

        from cygnusx.infrastructure.execution.langgraph_nodes import NodeDeps
        from cygnusx.infrastructure.execution.langgraph_runtime import (
            LangGraphRuntimeService,
        )

        def _find_server(tool_name: str) -> Any:
            return next(
                (
                    s
                    for s in runtime_state["active_mcp_servers"]
                    if any(t.tool_name == tool_name for t in s.tools)
                ),
                None,
            )

        def _resolve_channel(tool_name: str) -> str | None:
            if tool_name == HANDOFF_TOOL_NAME:
                return "handoff"
            if tool_name == CHAT_SANDBOX_TOOL_NAME:
                return "chat-sandbox"
            if tool_name == NETWORK_REQUEST_TOOL_NAME:
                return "network-request"
            if tool_name in SKILL_TOOL_NAMES:
                return "skills"
            if tool_name in RESEARCH_TOOL_NAMES:
                return RESEARCH_TOOL_CHANNEL
            server = _find_server(tool_name)
            return server.name if server else None

        async def _tool_executor(
            tool_name: str, args: dict[str, Any], tool_call_id: str
        ) -> dict[str, Any]:
            if tool_name == HANDOFF_TOOL_NAME:
                from cygnusx.application.services.tool_bridge_service import (
                    get_tool_bridge_service,
                )

                bridge_result = await get_tool_bridge_service().execute(
                    user_id=user_id,
                    tool_name=tool_name,
                    arguments=args,
                    context=runtime_state["tool_context"],
                )
                return {
                    "success": bool(bridge_result.get("success")),
                    "result": bridge_result,
                }
            if tool_name in SKILL_TOOL_NAMES:
                return await self._service._execute_skill_tool(
                    tool_name,
                    args,
                    runtime_state["skills"],
                    skill_pins=runtime_state.get("skill_pins"),
                )
            if tool_name == "ask_user":
                # 与 legacy stop_after_tools 同一信封；图经 state["ask_request"]
                # 结束后由下方产出 ask_request 事件并收尾本轮。
                questions = _normalize_ask_questions(args)
                first = questions[0]
                ask_payload: dict[str, Any] = {
                    "questions": questions,
                    "question": first["question"],
                    "options": first["options"],
                    "message": "问题已展示给用户，用户将在下一条消息中回答。本轮回复到此结束，请等待用户答复。",
                }
                return {
                    "success": True,
                    "result": {"llm_payload": ask_payload, "ui_payload": dict(ask_payload)},
                }
            if tool_name == SUBMIT_OUTPUT_TOOL_NAME:
                # 显式 Finalize 动作（openai4s 外循环三选一，§3.3.1）：模型提交
                # 最终答复并结束本轮；图经 state["finalize"] 收尾，output 由下方
                # 作为最终正文并入消息（携带完成语义，对标 host.submit_output）。
                output = str(args.get("output") or "")
                finalize_payload: dict[str, Any] = {
                    "output": output,
                    "message": "最终答复已提交，本轮结束。",
                }
                return {
                    "success": True,
                    "result": {
                        "llm_payload": finalize_payload,
                        "ui_payload": dict(finalize_payload),
                    },
                }
            if tool_name == "knowledge_search":
                session = await self._service.get_session(session_id, user_id)
                return await self._service._knowledge_search_chat(
                    args, project_id=session.project_id if session else None
                )
            if tool_name == "web_search":
                # 对齐 legacy chat_service.py:5038-5074：循环内补发 web_search
                # UI 事件（searching / sources / empty / failed），前端来源卡片依赖它们。
                query = str(args.get("query") or "")
                await _emit(
                    ChatChunk(
                        type="web_search",
                        content=query,
                        metadata={"status": "searching"},
                    )
                )
                result = await self._service._web_search(args)
                search_payload = result.get("result") if isinstance(result, dict) else None
                search_results = (
                    search_payload.get("results", []) if isinstance(search_payload, dict) else []
                )
                if isinstance(result, dict) and result.get("success") and isinstance(search_results, list):
                    persisted_web_sources.extend(
                        item for item in search_results if isinstance(item, dict)
                    )
                    if search_results:
                        await _emit(
                            ChatChunk(
                                type="web_search_results",
                                metadata={"sources": search_results},
                            )
                        )
                    else:
                        await _emit(
                            ChatChunk(
                                type="web_search",
                                content="未找到相关结果，已基于模型知识回答",
                                metadata={"status": "empty"},
                            )
                        )
                else:
                    await _emit(
                        ChatChunk(
                            type="web_search",
                            content="联网搜索失败，已基于模型自身知识回答",
                            metadata={"status": "failed"},
                        )
                    )
                return result
            if tool_name == NETWORK_REQUEST_TOOL_NAME:
                effective_args, rejection = await _gate_network_request_approval(
                    emit=_emit,
                    user_id=user_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    args=args,
                    permission_mode=chat_permission_mode,
                    always_allow=chat_always_allow,
                    auto_approve=auto_approve,
                )
                if rejection is not None:
                    return rejection
                return await execute_network_request(effective_args)
            if tool_name == CHAT_SANDBOX_TOOL_NAME:
                # 与 legacy 手写循环同一审批闸（supervised 模式经 Redis 审批 + SSE
                # 事件下发/决议回写，audit_logs 留痕）；决议通过后才执行。执行本体
                # 与 legacy 相同；LangGraph 执行器只回单个信封，不走
                # stream_chat_sandbox_tool 的增量 tool_output 事件（R13，见 ADR）。
                effective_args, rejection = await _gate_chat_sandbox_approval(
                    emit=_emit,
                    user_id=user_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    args=args,
                    permission_mode=chat_permission_mode,
                    always_allow=chat_always_allow,
                    auto_approve=auto_approve,
                )
                if rejection is not None:
                    return rejection
                return await execute_chat_sandbox(
                    effective_args, user_id, session_id=session_id
                )
            if tool_name == MAS_PLAN_PREVIEW_TOOL_NAME:
                # 对齐 legacy chat_service.py:4391-4392：adapt 返回的信封
                # （success/result 双通道）直接作为工具结果，不再二次封装。
                from cygnusx.application.services.mas_plan_adapter import (
                    MASPlanPreviewAdapter,
                )

                return MASPlanPreviewAdapter().adapt(args)
            if tool_name == PARALLEL_SUBAGENTS_TOOL_NAME:
                # 对齐 legacy chat_service.py:4408-4511 并行子 Agent fanout：
                # Case 绑定拒绝、每轮次数护栏、started/aggregated 事件与
                # 双通道信封封装逐点一致；fanout-ask 检测由 tool_result 消费
                # 分支（下方 494-499）自动完成，这里不再发 ask_request。
                tool_context = runtime_state["tool_context"]
                if tool_context.extra.get("agentteams_case_id"):
                    limit_error = (
                        "当前会话已绑定 AgentTeams Case；复杂协作由 Case Work Item 编排，"
                        "不会再通过 parallel_subagents 派生子 Agent。"
                    )
                    return {
                        "success": False,
                        "result": {
                            "llm_payload": {"success": False, "error": limit_error},
                            "ui_payload": {"error": limit_error},
                        },
                    }
                if (
                    subagent_calls_per_round["count"]
                    >= get_settings().subagent_max_children_per_message
                ):
                    limit_error = "本轮已执行过子 Agent 并行分派，请先消化汇总结果再决定下一步"
                    return {
                        "success": False,
                        "result": {
                            "llm_payload": {"success": False, "error": limit_error},
                            "ui_payload": {"error": limit_error},
                        },
                    }
                subagent_calls_per_round["count"] += 1
                fanout_tasks = [
                    item for item in (args.get("tasks") or []) if isinstance(item, dict)
                ]
                await _emit(
                    ChatChunk(
                        type="subagents",
                        metadata={
                            "phase": "started",
                            "tool_call_id": tool_call_id,
                            "tasks": [
                                {
                                    "index": fanout_index,
                                    "agent_id": str(item.get("agent_id") or ""),
                                    "task": str(item.get("task") or "")[:120],
                                }
                                for fanout_index, item in enumerate(fanout_tasks, start=1)
                            ],
                        },
                    )
                )
                if tool_context.extra.get("goal_id"):
                    from cygnusx.application.services.goal_adapters.fanout_adapter import (
                        GoalFanoutAdapter,
                    )

                    fanout_envelope = await GoalFanoutAdapter().execute(
                        context_summary=str(args.get("context_summary") or ""),
                        tasks=fanout_tasks,
                        context=tool_context,
                    )
                else:
                    from cygnusx.application.services.parallel_subagent_tool_service import (
                        ParallelSubAgentToolService,
                    )

                    fanout_envelope = (
                        await ParallelSubAgentToolService().run_parallel_subagents(
                            context_summary=str(args.get("context_summary") or ""),
                            tasks=fanout_tasks,
                            context=tool_context,
                        )
                    )
                await _emit(
                    ChatChunk(
                        type="subagents",
                        metadata={
                            "phase": "aggregated",
                            "tool_call_id": tool_call_id,
                            "success": bool(fanout_envelope.get("success")),
                            "summary": str(
                                (fanout_envelope.get("llm_payload") or {}).get("summary")
                                or ""
                            ),
                            "progress": (fanout_envelope.get("ui_payload") or {}).get(
                                "progress"
                            )
                            or [],
                        },
                    )
                )
                return {
                    "success": bool(fanout_envelope.get("success")),
                    "result": {
                        "llm_payload": fanout_envelope.get("llm_payload"),
                        "ui_payload": fanout_envelope.get("ui_payload"),
                    },
                }
            if tool_name == "create_agentteams_case":
                # 对齐 legacy chat_service.py:4512-4584：未确认时经 ToolBridge 预检
                # （needs_confirm 时登记确认请求并并入 ui_payload），已确认时
                # 直调 AgentTeamsCaseToolService.run 并下发 agentteams_case 卡片事件。
                from cygnusx.application.services.agentteams_case_tool_service import (
                    AgentTeamsCaseToolService,
                )
                from cygnusx.application.services.tool_bridge_service import (
                    get_tool_bridge_service,
                )

                tool_context = runtime_state["tool_context"]
                if not args.get("_confirmed"):
                    bridge_result = await get_tool_bridge_service().execute(
                        user_id=user_id,
                        tool_name=tool_name,
                        arguments=args,
                        context=tool_context,
                    )
                    if (bridge_result.get("llm_payload") or {}).get("needs_confirm"):
                        confirmation = (
                            await AgentTeamsCaseToolService().record_confirmation_request(
                                objective=str(args.get("objective") or ""),
                                project_id=str(args.get("project_id") or ""),
                                flow_id=str(args.get("flow_id") or ""),
                                origin_consultation_id=str(
                                    args.get("origin_consultation_id") or ""
                                )
                                or None,
                                consultation_summary=str(
                                    args.get("consultation_summary") or ""
                                )
                                or None,
                                context=tool_context,
                            )
                        )
                        bridge_result = {
                            **bridge_result,
                            "ui_payload": {
                                **dict(bridge_result.get("ui_payload") or {}),
                                "agentteams_case_confirmation": confirmation,
                            },
                        }
                    return {
                        "success": bool(bridge_result.get("success")),
                        "result": bridge_result,
                    }
                case_envelope = await AgentTeamsCaseToolService().run(
                    objective=str(args.get("objective") or ""),
                    project_id=str(args.get("project_id") or ""),
                    flow_id=str(args.get("flow_id") or ""),
                    sample_context_refs=args.get("sample_context_refs") or [],
                    origin_consultation_id=str(args.get("origin_consultation_id") or "")
                    or None,
                    consultation_summary=str(args.get("consultation_summary") or "")
                    or None,
                    context=tool_context,
                )
                card = (case_envelope.get("ui_payload") or {}).get("case_card") or {}
                await _emit(
                    ChatChunk(
                        type="agentteams_case",
                        metadata={
                            "phase": "created",
                            "tool_call_id": tool_call_id,
                            "session_id": session_id,
                            "message_id": ai_message_id,
                            **card,
                        },
                    )
                )
                return {
                    "success": bool(case_envelope.get("success")),
                    "result": {
                        "llm_payload": case_envelope.get("llm_payload"),
                        "ui_payload": case_envelope.get("ui_payload"),
                    },
                }
            if tool_name in {"goal_complete", "goal_blocked"}:
                # 对齐 legacy chat_service.py:5026-5033：goal 终态工具直调
                # GoalTerminalToolService（execute 已返回完整双通道信封）。
                from cygnusx.application.services.goal_terminal_tools import (
                    GoalTerminalToolService,
                )

                return await GoalTerminalToolService().execute(
                    tool_name, args, runtime_state["tool_context"]
                )
            server = _find_server(tool_name)
            if server is None:
                return {"success": False, "error": f"工具 {tool_name} 未挂载到该 Agent"}
            return await mcp_client.call_tool(
                server,
                tool_name,
                args,
                user_id=user_id,
                context=runtime_state["tool_context"],
            )

        full_content = ""
        update_counter = 0
        first_chunk_sent = False
        accumulated_usage: dict[str, Any] | None = None
        # 轮次上限与手写循环对齐：默认 100 轮；前端弹窗确认继续后传
        # extend_max_rounds=True 扩展到 1000 轮。
        max_rounds = 1000 if extend_max_rounds else 100
        # 历史重载重建工具卡片/图表所需（对齐 legacy 手写循环）：
        # timeline 记录正文段/工具段的交错顺序，persisted_tool_invocations 保存
        # 每次工具调用的 arguments/result/ui_payload——Plotly 图表等就在 ui_payload 里，
        # 不落库则重开会话后卡片与图全部丢失。
        persisted_tool_invocations: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        timeline_text_buffer = ""
        pending_tool_args: dict[str, dict[str, Any]] = {}
        pending_fanout_ask: dict[str, Any] | None = None
        # 终止态标记：ask_user / fanout 澄清收尾时置 True，
        # agent_final_result 据此发 awaiting_input（对齐 legacy 5464/5468）。
        terminal_awaiting_input = False
        # 显式 Finalize 动作标记：submit_output 收尾时置 True，
        # agent_final_result 据此携带 action="finalize"（§3.3.1）。
        terminal_finalize = False
        execution_path = "chat_langgraph"
        execution_run_id = f"agent-langgraph:{ai_message_id}"
        execution_agent_id = str(
            getattr(tool_context, "agent_id", None)
            or getattr(getattr(tool_context, "agent", None), "agent_id", None)
            or "router"
        )
        execution_round = 0
        # 并行子 Agent fanout 每轮（一次图运行）次数护栏（对齐 legacy
        # chat_service.py:4190 的 subagent_calls_this_round 每轮重置语义）：
        # _tool_executor 在 while True 循环外定义、跨轮复用，故计数器需在
        # 每次图运行开始时重置（参照 execution_round 的处理方式）。
        subagent_calls_per_round: dict[str, int] = {"count": 0}
        # WP3-Task1：cell 编号基线取本会话已落库信封的最大 cell_index+1
        # （纯派生，对齐 legacy chat_service.py:3956；查询失败时从 0 起，
        # 不阻断聊天主链路）
        try:
            code_cell_next = _max_persisted_cell_index(
                await self._service._sessions.get_messages(session_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cell_index 基线查询失败，从 0 起编号: {}", exc)
            code_cell_next = 0

        yield execution_chunk(
            "agent_turn_started",
            session_id=session_id,
            run_id=execution_run_id,
            agent_id=execution_agent_id,
            round_number=0,
            execution_path=execution_path,
            message_id=ai_message_id,
            tool_count=len(tools),
        )

        def _flush_timeline_text() -> None:
            nonlocal timeline_text_buffer
            text = timeline_text_buffer
            timeline_text_buffer = ""
            if text:
                timeline.append({"kind": "text", "text": text})

        def _failed_terminal_events(error: str) -> tuple[ChatChunk, ChatChunk]:
            return (
                execution_chunk(
                    "agent_turn_failed",
                    session_id=session_id,
                    run_id=execution_run_id,
                    agent_id=execution_agent_id,
                    round_number=execution_round,
                    execution_path=execution_path,
                    error=error,
                ),
                ChatChunk(
                    type="done",
                    metadata={
                        "session_id": session_id,
                        "message_id": ai_message_id,
                        "status": "error",
                    },
                ),
            )

        try:
            while True:
                # 每次图运行（一轮）开始时重置并行子 Agent fanout 计数器，
                # 对齐 legacy chat_service.py:4190 的 subagent_calls_this_round。
                subagent_calls_per_round["count"] = 0
                # 显式 Finalize 动作（submit_output，§3.3.1）随 Runtime 挂载（幂等）：
                # 仅 LangGraph 路径下发给模型，legacy 逃生舱不识别本工具。
                runtime_tools = runtime_state["tools"]
                if runtime_tools and not any(
                    (t.get("function") or {}).get("name") == SUBMIT_OUTPUT_TOOL_NAME
                    for t in runtime_tools
                    if isinstance(t, dict)
                ):
                    runtime_state["tools"] = [*runtime_tools, SUBMIT_OUTPUT_TOOL_SCHEMA]
                deps = NodeDeps(
                    model_config=runtime_state["model_config"],
                    system_prompt=runtime_state["system_prompt"],
                    temperature=runtime_state["temperature"],
                    max_tokens=runtime_state["max_tokens"],
                    tools=runtime_state["tools"] or None,
                    deep_thinking=deep_thinking,
                    tool_executor=_tool_executor,
                    channel_resolver=_resolve_channel,
                    chat_stream=provider_manager.chat_stream,
                    emit_execution_events=True,
                    session_id=session_id,
                    run_id=execution_run_id,
                    agent_id=execution_agent_id,
                    execution_path=execution_path,
                )
                deps_holder["deps"] = deps
                runtime = LangGraphRuntimeService(deps, max_rounds=max_rounds)
                async for chunk in runtime.stream(runtime_state["llm_messages"]):
                    if chunk.type == "text":
                        if chunk.metadata.get("is_reasoning"):
                            # 推理过程不并入最终正文，但仍透传给前端
                            yield chunk
                            continue
                        full_content += chunk.content
                        timeline_text_buffer += chunk.content
                        update_counter += 1
                        if update_counter % 5 == 0:
                            await self._service.update_message_content(
                                ai_message_id, full_content, "streaming"
                            )
                        if not first_chunk_sent:
                            chunk.metadata["session_id"] = session_id
                            chunk.metadata["message_id"] = ai_message_id
                            first_chunk_sent = True
                        yield chunk
                    elif chunk.type == "error":
                        error = chunk.content or "LangGraph Runtime 返回错误"
                        # 正文保留已累计内容，错误原因写入 metadata.error
                        await self._service.update_message_content(
                            ai_message_id,
                            full_content,
                            "error",
                            {"error": error},
                        )
                        yield chunk
                        for terminal_chunk in _failed_terminal_events(error):
                            yield terminal_chunk
                        return
                    elif chunk.type == "tool_call":
                        execution_round = max(execution_round, int(chunk.metadata.get("round") or 1))
                        chunk.metadata.update(
                            {
                                "execution_path": execution_path,
                                "run_id": execution_run_id,
                                "round": execution_round,
                            }
                        )
                        # 正文段在工具调用前收口，保持"正文→工具"交错顺序
                        _flush_timeline_text()
                        tc_meta = chunk.metadata or {}
                        call_id = tc_meta.get("tool_call_id", "")
                        if call_id:
                            pending_tool_args[call_id] = tc_meta.get("arguments", {}) or {}
                        yield chunk
                    elif chunk.type == "tool_result":
                        tc_meta = chunk.metadata or {}
                        chunk.metadata.update(
                            {
                                "execution_path": execution_path,
                                "run_id": execution_run_id,
                                "round": execution_round,
                            }
                        )
                        call_id = tc_meta.get("tool_call_id", "")
                        tool_name = tc_meta.get("tool_name", "")
                        success = bool(tc_meta.get("success"))
                        llm_result = tc_meta.get("result")
                        ui_payload = tc_meta.get("ui_payload")
                        timeline.append(
                            {
                                "kind": "tool",
                                "tool_call_id": call_id,
                                "tool_name": tool_name,
                            }
                        )
                        # 信封落库对齐 legacy chat_service.py:5209-5249：带截断元信息
                        # 的落库护栏、cell 语义字段与 payload_hash(WP2 可校验)。
                        # 历史重载凭这些字段重建卡片/图表并显式提示截断。
                        args = pending_tool_args.pop(call_id, {})
                        capped_result, result_truncation = _cap_tool_invocation_payload_detail(llm_result)
                        capped_ui_payload, ui_payload_truncation = _cap_tool_invocation_payload_detail(
                            ui_payload
                        )
                        _invocation_envelope: dict[str, Any] = {
                            "tool_call_id": call_id,
                            "tool_name": tool_name,
                            "arguments": args,
                            "success": success,
                            "result": capped_result,
                            "ui_payload": capped_ui_payload,
                            **(
                                {"result_truncation": result_truncation}
                                if result_truncation
                                else {}
                            ),
                            **(
                                {"ui_payload_truncation": ui_payload_truncation}
                                if ui_payload_truncation
                                else {}
                            ),
                            "mcp_server": tc_meta.get("mcp_server"),
                            **(
                                {"reliability": tc_meta["reliability"]}
                                if tc_meta.get("reliability") is not None
                                else {}
                            ),
                            # cell 字段在 payload_hash 计算前写入，hash 覆盖 cell_index/
                            # language（对齐 legacy 5238-5243）
                            **(_cell_fields := _code_cell_envelope_fields(
                                tool_name, args, code_cell_next
                            )),
                        }
                        if _cell_fields["cell_index"] is not None:
                            code_cell_next += 1
                        _invocation_envelope["payload_hash"] = _invocation_payload_hash(
                            _invocation_envelope
                        )
                        persisted_tool_invocations.append(_invocation_envelope)
                        if tool_name == PARALLEL_SUBAGENTS_TOOL_NAME and isinstance(llm_result, dict):
                            fanout_envelope = {
                                "llm_payload": llm_result.get("llm_payload"),
                                "ui_payload": ui_payload,
                            }
                            pending_fanout_ask = _fanout_ask_request(fanout_envelope)
                        await self._service.update_message_content(
                            ai_message_id,
                            full_content,
                            "streaming",
                            {
                                "tool_invocations": persisted_tool_invocations,
                                "timeline": timeline,
                            },
                        )
                        yield chunk
                    else:
                        # 其余事件直接透传（metadata 已对齐 legacy）
                        yield chunk

                accumulated_usage = merge_token_usage(accumulated_usage, runtime.last_usage)
                # ask_user 澄清：问题经 ask_request 事件展示给用户，收尾本轮，
                # 等用户下一条消息回答（对齐 legacy stop_after_tools 语义）。
                ask_request = runtime.last_ask_request
                if ask_request is not None:
                    terminal_awaiting_input = True
                    _flush_timeline_text()
                    questions = _normalize_ask_questions(ask_request.get("args") or {})
                    first = questions[0]
                    # ask_user 工具调用已在上方 tool_result 分支落库；这里把最终
                    # timeline 随完成态一并写入，保证历史重载能重建澄清卡片。
                    await self._service.update_message_content(
                        ai_message_id,
                        full_content,
                        "complete",
                        {
                            **({"usage": accumulated_usage} if accumulated_usage else {}),
                            **({"timeline": timeline} if timeline else {}),
                        }
                        or None,
                    )
                    yield ChatChunk(
                        type="ask_request",
                        metadata={
                            "tool_call_id": ask_request.get("tool_call_id", ""),
                            "questions": questions,
                            # 兼容旧前端：首问题的平铺字段
                            "question": first["question"],
                            "options": first["options"],
                        },
                    )
                    break
                # 显式 Finalize 动作（submit_output）：把模型提交的答复作为最终
                # 正文并入消息（文本块透传给前端并落库），随后正常收尾本轮。
                finalize_request = runtime.last_finalize
                if finalize_request is not None and runtime.last_handoff is None:
                    finalize_output = str(finalize_request.get("output") or "")
                    if finalize_output:
                        terminal_finalize = True
                        if full_content and not full_content.endswith("\n"):
                            full_content += "\n"
                        full_content += finalize_output
                        timeline_text_buffer += finalize_output
                        await self._service.update_message_content(
                            ai_message_id, full_content, "streaming"
                        )
                        yield ChatChunk(
                            type="text",
                            content=finalize_output,
                            metadata={"session_id": session_id, "message_id": ai_message_id},
                        )
                    break
                if pending_fanout_ask is not None:
                    terminal_awaiting_input = True
                    _flush_timeline_text()
                    first = pending_fanout_ask["questions"][0]
                    yield ChatChunk(
                        type="ask_request",
                        metadata={
                            "tool_call_id": "",
                            **pending_fanout_ask,
                            "question": first["question"],
                            "options": first["options"],
                        },
                    )
                    pending_fanout_ask = None
                    await self._service.update_message_content(
                        ai_message_id,
                        full_content,
                        "complete",
                        {"timeline": timeline} if timeline else None,
                    )
                    break
                directive = runtime.last_handoff
                if directive is None:
                    break
                if handoff_handler is None:
                    error = "Agent 转交未被当前运行时处理"
                    await self._service.update_message_content(
                        ai_message_id,
                        full_content,
                        "error",
                        {"error": error},
                    )
                    yield ChatChunk(type="error", content=error)
                    for terminal_chunk in _failed_terminal_events(error):
                        yield terminal_chunk
                    return
                next_state = await handoff_handler(directive)
                runtime_state.update(next_state)
                execution_round += 1
                yield execution_chunk(
                    "agent_turn_continued",
                    session_id=session_id,
                    run_id=execution_run_id,
                    agent_id=execution_agent_id,
                    round_number=execution_round,
                    execution_path=execution_path,
                    reason="handoff",
                )
                yield ChatChunk(
                    type="handoff",
                    metadata={
                        **directive,
                        "session_id": session_id,
                        "message_id": ai_message_id,
                    },
                )
            if (
                not full_content.strip()
                and runtime.last_handoff is None
                and runtime.last_ask_request is None
            ):
                diagnostic = (
                    "模型请求已完成，但没有返回可展示的正文；"
                    f"model={runtime_state['model_config'].model}, "
                    f"usage={accumulated_usage or {}}, runtime_error={runtime.error or ''}"
                )
                logger.error("[Agent空响应] session={} {}", session_id, diagnostic)
                await self._service.update_message_content(
                    ai_message_id,
                    diagnostic,
                    "error",
                    {"error": diagnostic, "usage": accumulated_usage or {}},
                )
                yield ChatChunk(
                    type="error",
                    content="模型完成了请求，但没有返回正文。请稍后重试；若持续出现，请检查模型的思考开关和输出上限。",
                    metadata={
                        "session_id": session_id,
                        "message_id": ai_message_id,
                        "model": runtime_state["model_config"].model,
                        "usage": accumulated_usage or {},
                    },
                )
                yield execution_chunk(
                    "agent_turn_failed",
                    session_id=session_id,
                    run_id=execution_run_id,
                    agent_id=execution_agent_id,
                    round_number=execution_round,
                    execution_path=execution_path,
                    error=diagnostic,
                )
                yield ChatChunk(
                    type="done",
                    metadata={
                        "session_id": session_id,
                        "message_id": ai_message_id,
                        "status": "error",
                    },
                )
                return
        except Exception as e:  # noqa: BLE001
            error = str(e)
            await self._service.update_message_content(
                ai_message_id,
                full_content,
                "error",
                {"error": error},
            )
            yield ChatChunk(
                type="error",
                content=f"生成失败: {error}",
                metadata={
                    "session_id": session_id,
                    "message_id": ai_message_id,
                    **execution_metadata(
                        "agent_turn_failed",
                        session_id=session_id,
                        run_id=execution_run_id,
                        agent_id=execution_agent_id,
                        round_number=execution_round,
                        execution_path=execution_path,
                        error=error,
                    ),
                },
            )
            for terminal_chunk in _failed_terminal_events(error):
                yield terminal_chunk
            return

        # 收尾：complete + usage + 会话用量累计 + done（与 legacy 一致）
        _flush_timeline_text()
        last_usage = accumulated_usage
        await self._service.update_message_content(
            ai_message_id,
            full_content,
            "complete",
            {
                **({"usage": last_usage} if last_usage else {}),
                **({"web_sources": persisted_web_sources} if persisted_web_sources else {}),
                **({"timeline": timeline} if timeline else {}),
                **suggestions_metadata(full_content),
            }
            or None,
        )
        if (
            runtime.rounds_exhausted
            and runtime.last_handoff is None
            and runtime.last_ask_request is None
        ):
            # 轮次触顶：与手写循环一致，通知前端弹窗选择是否以扩展上限继续
            yield ChatChunk(
                type="round_limit",
                content=f"工具调用轮次达到上限（{max_rounds}），任务提前结束",
                metadata={
                    "session_id": session_id,
                    "message_id": ai_message_id,
                    "max_rounds": max_rounds,
                    "can_extend": max_rounds < 1000,
                },
            )
        await self._service._apply_usage_to_session(ai_message_id, last_usage)
        yield execution_chunk(
            "agent_final_result",
            session_id=session_id,
            run_id=execution_run_id,
            agent_id=execution_agent_id,
            round_number=execution_round,
            execution_path=execution_path,
            message_id=ai_message_id,
            status=(
                "round_limit"
                if runtime.rounds_exhausted
                else "awaiting_input" if terminal_awaiting_input else "completed"
            ),
            **({"action": "finalize"} if terminal_finalize else {}),
        )
        yield ChatChunk(
            type="done",
            metadata={
                "session_id": session_id,
                "message_id": ai_message_id,
                "usage": last_usage,
                **suggestions_metadata(full_content),
            },
        )
