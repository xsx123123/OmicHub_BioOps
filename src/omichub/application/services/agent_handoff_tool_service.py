"""将 Agent Handoff 请求接入 ToolBridge。"""

from __future__ import annotations

from typing import Any

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.agent_handoff_service import AgentHandoffService
from omichub.core.exceptions import BusinessError


class AgentHandoffToolService:
    """只生成已校验的交接指令；实际切换由 ChatService 完成。"""

    async def transfer_to_agent(
        self,
        *,
        user_id: str,
        target_agent: str,
        reason: str,
        handoff_summary: str,
        user_intent: str,
        artifacts: list[str] | None = None,
        constraints: list[str] | None = None,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if context is None or not context.agent_id or not context.session_id:
            raise BusinessError("Agent 转交工具需要受控的会话调用上下文")
        directive = await AgentHandoffService(context.db).prepare_handoff(
            user_id=user_id,
            session_id=context.session_id,
            source_agent_id=context.agent_id,
            target_agent_id=target_agent,
            reason=reason,
            handoff_summary=handoff_summary,
            user_intent=user_intent,
            artifacts=artifacts,
            constraints=constraints,
        )
        return {
            "success": True,
            "handoff": directive,
            "summary": f"已准备转交给 {directive['target_agent_name']}。",
        }
