"""Goal-only terminal tools, dynamically exposed by the Goal runtime."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.goal_evaluator import GoalEvaluator
from omichub.infrastructure.database.models.goal import AgentGoalModel

GOAL_COMPLETE_TOOL_NAME = "goal_complete"
GOAL_BLOCKED_TOOL_NAME = "goal_blocked"
GOAL_TERMINAL_TOOL_NAMES = {GOAL_COMPLETE_TOOL_NAME, GOAL_BLOCKED_TOOL_NAME}
GOAL_TERMINAL_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": GOAL_COMPLETE_TOOL_NAME,
            "description": "仅当每条 Goal 成功标准已有可验证证据时调用，结束当前 Goal。",
            "parameters": {
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterion": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["criterion", "evidence"],
                        },
                    },
                    "reason": {"type": "string"},
                },
                "required": ["evidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": GOAL_BLOCKED_TOOL_NAME,
            "description": "仅当 Goal 无法在现有权限、输入或外部状态下继续时调用。",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


class GoalTerminalToolService:
    async def execute(
        self, tool_name: str, arguments: dict[str, Any], context: ToolInvocationContext
    ) -> dict[str, Any]:
        goal = await self._owned_manager_goal(context)
        if tool_name == GOAL_COMPLETE_TOOL_NAME:
            evidence = arguments.get("evidence")
            if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
                return self._error("goal_complete 必须提供结构化 evidence")
            normalized = [dict(item) for item in evidence]
            if not GoalEvaluator().validates_completion(goal.success_criteria, normalized):
                return self._error("Goal 成功标准尚未全部获得有效证据")
            return self._success("complete", evidence=normalized, reason=str(arguments.get("reason") or ""))
        if tool_name == GOAL_BLOCKED_TOOL_NAME:
            reason = str(arguments.get("reason") or "").strip()
            if not reason:
                return self._error("goal_blocked 必须说明阻塞原因")
            return self._success("blocked", evidence=[], reason=reason)
        return self._error(f"未知 Goal 终结工具: {tool_name}")

    @staticmethod
    async def _owned_manager_goal(context: ToolInvocationContext) -> AgentGoalModel:
        raw_goal_id = context.extra.get("goal_id")
        try:
            goal_id = UUID(str(raw_goal_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("Goal 终结工具只能在 Goal Runtime 中调用") from exc
        goal = (
            await context.db.execute(
                select(AgentGoalModel).where(
                    AgentGoalModel.id == goal_id,
                    AgentGoalModel.status == "in_progress",
                )
            )
        ).scalar_one_or_none()
        if goal is None or str(goal.user_id) != context.user_id:
            raise ValueError("Goal 不存在、已终结或无权访问")
        if context.agent_id != goal.manager_agent_id:
            raise ValueError("只有 Goal Manager 可以终结 Goal")
        return goal

    @staticmethod
    def _success(action: str, evidence: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        payload = {"action": action, "evidence": evidence, "reason": reason}
        return {"success": True, "result": {"llm_payload": payload, "ui_payload": payload}}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"success": False, "error": message, "result": {"llm_payload": {"error": message}}}
