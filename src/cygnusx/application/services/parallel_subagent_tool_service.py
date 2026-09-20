"""将并行子 Agent 分派接入工具体系。

调用路径说明（与 transfer_to_agent 的桥路由不同）：
chat_service 对 parallel_subagents 采用 mas_plan_preview 同款「特判直调」，
不经 ToolBridgeService._package——其 llm_payload 3KB 硬上限会把多子任务汇总
截断为占位文本。schema 注册仍然保留：它是 assemble_context 经
schema_loader.to_openai_tools() 向 LLM 暴露工具的通行证。
"""

from __future__ import annotations

from typing import Any

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.parallel_subagent_service import ParallelSubAgentService
from cygnusx.core.exceptions import BusinessError


class ParallelSubAgentToolService:
    """工具薄壳：校验受控会话上下文后委派给 ParallelSubAgentService。"""

    async def run_parallel_subagents(
        self,
        *,
        context_summary: str = "",
        tasks: list[dict[str, Any]] | None = None,
        context: ToolInvocationContext | None = None,
        on_event: Any = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if context is None or not context.user_id or not context.session_id:
            raise BusinessError("子 Agent 分派工具需要受控的会话调用上下文")
        return await ParallelSubAgentService().run(
            user_id=context.user_id,
            parent_agent_id=context.agent_id or "",
            parent_session_id=context.session_id,
            context_summary=context_summary or "",
            tasks=tasks or [],
            db=context.db,
            on_event=on_event,
            safe_only=bool(context.extra.get("goal_safe_only")),
        )
