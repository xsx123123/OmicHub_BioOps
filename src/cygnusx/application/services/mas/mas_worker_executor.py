"""Worker 执行器（手册 2.3）：一次完整 Worker turn 委托既有 LangGraph 运行时。

- assemble_context 装配目标 Agent（agent_service.assemble_context）
- 构造 ChatRuntimeRequest（必填仅 user_id/agent_id/messages，阶段 0 核实）
- 委托 LangGraphChatRuntime.run()，逐 chunk emit 到房间 SSE 并收集最终文本
- 任何异常返回错误信封文本，不向上抛
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from cygnusx.domain.mas.worker_policy import strip_worker_tools

logger = logging.getLogger(__name__)

# emit 回调：接收 (room_id, ChatChunk-like dict)；由 mas_room_service 注入
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]

# 最近一次 worker turn 的 token usage（进程内单 run 串行执行；并发时最后写入者胜，
# 精确 per-turn 归属阶段 5 扩展为返回值传递）
_last_usage_meta: dict[str, Any] = {}


def last_turn_usage() -> dict[str, Any]:
    """返回最近一次 worker turn 的 token usage（落消息 metadata 用）。"""
    return dict(_last_usage_meta)


async def run_worker_turn(
    agent_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    emit: EmitFn,
    room_id: str,
) -> str:
    """执行一个 Worker turn，返回最终 assistant 文本（失败时返回错误信封文本）。

    1. assemble_context 装配目标 Agent（不存在/未启用 → 错误信封）
    2. 构造 ChatRuntimeRequest 并委托 LangGraphChatRuntime.run()
    3. 逐 chunk emit() 透传给房间 SSE（打字机实时性）
    4. 收集最终 assistant 文本作为返回值；绝不抛异常
    """
    try:
        from cygnusx.application.services.agent_service import AgentService
        from cygnusx.application.services.chat.runtimes.langgraph_runtime import (
            LangGraphChatRuntime,
        )
        from cygnusx.application.services.chat_service import ChatService
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            agent_service = AgentService(session)
            # 底层 chat 链路（cookie 余额/用户能力）要求真实 UUID user_id；
            # 非 UUID（冒烟/匿名）直接产出错误信封，不发起调用（红线：不改既有链路）。
            try:
                uuid.UUID(str(user_id))
            except ValueError:
                error_text = "无法确定执行者身份（user_id 非法），已跳过该成员执行。"
                await emit(room_id, {"type": "error", "content": error_text})
                return error_text
            capability_user_id = user_id
            assembled = await agent_service.assemble_context(agent_id, capability_user_id)
            if assembled is None:
                error_text = f"部门成员 {agent_id} 不存在或未启用，无法执行该任务。"
                await emit(room_id, {"type": "error", "content": error_text})
                return error_text

            # 剥离递归/交接特性（Worker 内不允许再派生子 Agent）
            stripped_features = strip_worker_tools(assembled.features)

            chat_service = ChatService(session)
            runtime = LangGraphChatRuntime(chat_service)
            from cygnusx.application.services.chat.runtimes.base import ChatRuntimeRequest

            request = ChatRuntimeRequest(
                user_id=capability_user_id,
                agent_id=agent_id,
                messages=messages,
                mode="chat",
            )
            final_parts: list[str] = []
            usage_meta: dict[str, Any] = {}
            async for chunk in runtime.run(request):
                chunk_type = chunk.type
                # 透传文本增量给房间 SSE（打字机）
                if chunk_type == "text" and chunk.content:
                    final_parts.append(chunk.content)
                    await emit(
                        room_id,
                        {
                            "type": "text",
                            "agent_id": agent_id,
                            "content": chunk.content,
                        },
                    )
                elif chunk_type in ("error",):
                    await emit(room_id, {"type": "error", "content": chunk.content})
                elif chunk_type == "done":
                    # token usage 每个 turn 落消息 metadata（阶段 4）
                    usage = (chunk.metadata or {}).get("usage")
                    if usage:
                        usage_meta.update(usage)
                # 其它事件不透传（房间 SSE 由 run 终态统一发 done）

            final_text = "".join(final_parts).strip()
            if not final_text:
                final_text = "该成员暂未产出有效回复，请稍后重试或换一位成员。"
            _last_usage_meta.clear()
            _last_usage_meta.update(usage_meta)
            return final_text
    except Exception as exc:  # noqa: BLE001 - 故障兜底是硬要求
        logger.exception("MAS worker turn failed agent_id={} room={}", agent_id, room_id)
        error_text = f"执行出错：{exc}"
        try:
            await emit(room_id, {"type": "error", "content": error_text})
        except Exception:  # pragma: no cover
            pass
        return error_text
