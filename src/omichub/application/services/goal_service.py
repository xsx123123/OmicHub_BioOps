"""Lifecycle service for persistent Goal records and their audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.goal import (
    GoalAnswerRequest,
    GoalControlRequest,
    GoalEventPage,
    GoalResponse,
    GoalStartRequest,
    event_to_response,
    goal_to_response,
)
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.infrastructure.database.models.agent import AgentTemplateModel
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.models.goal import AgentGoalEventModel, AgentGoalModel

_TERMINAL_STATUSES = {"completed", "blocked", "cancelled", "failed"}


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _ensure_enabled() -> None:
        if not get_settings().goal_runtime_enabled:
            raise BusinessError("Goal Runtime 功能尚未启用")

    async def create_goal(self, user_id: str, request: GoalStartRequest) -> GoalResponse:
        self._ensure_enabled()
        manager_agent_id = request.manager_agent_id.strip() or "agent-general"
        if request.mode != "chat" or request.permission != "safe":
            raise BusinessError("Goal Runtime 第一阶段仅支持 chat + safe；Studio/写操作需等待后续受控阶段")
        chat_session = (
            await self._session.execute(
                select(ChatSessionModel).where(
                    ChatSessionModel.session_id == request.session_id,
                    ChatSessionModel.user_id == user_id,
                    ChatSessionModel.status == "active",
                )
            )
        ).scalar_one_or_none()
        if chat_session is None:
            raise NotFoundError("聊天会话不存在或无权作为 Goal 运行上下文")
        manager_agent = (
            await self._session.execute(
                select(AgentTemplateModel).where(
                    AgentTemplateModel.agent_id == manager_agent_id,
                    AgentTemplateModel.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if manager_agent is None:
            raise BusinessError("Goal Manager Agent 不存在或未启用")
        goal = AgentGoalModel(
            user_id=UUID(user_id),
            session_id=request.session_id,
            manager_agent_id=manager_agent_id,
            objective=request.objective,
            success_criteria=request.success_criteria,
            mode=request.mode,
            permission=request.permission,
            max_turns=request.max_turns,
            token_budget=request.token_budget,
            deadline_at=request.deadline_at,
            status="in_progress",
            started_at=datetime.now(UTC),
        )
        self._session.add(goal)
        await self._session.flush()
        await self._append_event(
            goal,
            "created",
            {
                "objective": goal.objective,
                "manager_agent_id": goal.manager_agent_id,
                "max_turns": goal.max_turns,
            },
        )
        return goal_to_response(goal)

    async def get_goal(self, user_id: str, goal_id: UUID) -> GoalResponse:
        self._ensure_enabled()
        return goal_to_response(await self._owned_goal(user_id, goal_id))

    async def list_goals(self, user_id: str, session_id: str | None = None) -> list[GoalResponse]:
        self._ensure_enabled()
        statement = select(AgentGoalModel).where(AgentGoalModel.user_id == UUID(user_id))
        if session_id is not None:
            statement = statement.where(AgentGoalModel.session_id == session_id)
        result = await self._session.execute(statement.order_by(AgentGoalModel.updated_at.desc()))
        return [goal_to_response(goal) for goal in result.scalars()]

    async def pause_goal(
        self, user_id: str, goal_id: UUID, request: GoalControlRequest
    ) -> GoalResponse:
        return await self._transition(user_id, goal_id, request.reason, "paused", {"in_progress"})

    async def resume_goal(
        self, user_id: str, goal_id: UUID, request: GoalControlRequest
    ) -> GoalResponse:
        return await self._transition(user_id, goal_id, request.reason, "in_progress", {"paused"})

    async def answer_goal(
        self, user_id: str, goal_id: UUID, request: GoalAnswerRequest
    ) -> GoalResponse:
        self._ensure_enabled()
        goal = await self._owned_goal(user_id, goal_id, for_update=True)
        if goal.status != "waiting_user":
            raise BusinessError("当前 Goal 未在等待用户输入")
        snapshot = dict(goal.plan_snapshot or {})
        pending_request = snapshot.pop("pending_user_request", None)
        snapshot["latest_user_answer"] = {
            "answer": request.answer,
            "request": pending_request,
            "answered_at": datetime.now(UTC).isoformat(),
        }
        goal.plan_snapshot = snapshot
        goal.status = "in_progress"
        goal.version += 1
        goal.lease_owner = None
        goal.lease_expires_at = None
        await self._append_event(
            goal,
            "user_answered",
            {"answer": request.answer, "request": pending_request},
        )
        return goal_to_response(goal)

    async def cancel_goal(
        self, user_id: str, goal_id: UUID, request: GoalControlRequest
    ) -> GoalResponse:
        return await self._transition(
            user_id,
            goal_id,
            request.reason,
            "cancelled",
            {"draft", "in_progress", "paused", "waiting_user"},
        )

    async def list_events(
        self, user_id: str, goal_id: UUID, after: int = 0, limit: int = 100
    ) -> GoalEventPage:
        self._ensure_enabled()
        await self._owned_goal(user_id, goal_id)
        result = await self._session.execute(
            select(AgentGoalEventModel)
            .where(AgentGoalEventModel.goal_id == goal_id, AgentGoalEventModel.sequence > after)
            .order_by(AgentGoalEventModel.sequence)
            .limit(limit + 1)
        )
        rows = list(result.scalars())
        has_next = len(rows) > limit
        rows = rows[:limit]
        return GoalEventPage(
            items=[event_to_response(event) for event in rows],
            next_cursor=rows[-1].sequence if has_next and rows else None,
        )

    async def _transition(
        self,
        user_id: str,
        goal_id: UUID,
        reason: str,
        target: str,
        allowed_sources: set[str],
    ) -> GoalResponse:
        self._ensure_enabled()
        goal = await self._owned_goal(user_id, goal_id, for_update=True)
        if goal.status not in allowed_sources:
            raise BusinessError(f"当前 Goal 状态 {goal.status} 不允许切换到 {target}")
        goal.status = target
        goal.version += 1
        goal.lease_owner = None
        goal.lease_expires_at = None
        if target in _TERMINAL_STATUSES:
            goal.completed_at = datetime.now(UTC)
        await self._append_event(goal, target, {"reason": reason})
        return goal_to_response(goal)

    async def _owned_goal(
        self, user_id: str, goal_id: UUID, *, for_update: bool = False
    ) -> AgentGoalModel:
        statement = select(AgentGoalModel).where(
            AgentGoalModel.id == goal_id, AgentGoalModel.user_id == UUID(user_id)
        )
        if for_update:
            statement = statement.with_for_update()
        goal = (await self._session.execute(statement)).scalar_one_or_none()
        if goal is None:
            raise NotFoundError("Goal 不存在或无权访问")
        return goal

    async def _append_event(
        self,
        goal: AgentGoalModel,
        event_type: str,
        payload: dict,
        *,
        dedupe_key: str | None = None,
    ) -> AgentGoalEventModel:
        if dedupe_key:
            existing = (
                await self._session.execute(
                    select(AgentGoalEventModel).where(
                        AgentGoalEventModel.goal_id == goal.id,
                        AgentGoalEventModel.dedupe_key == dedupe_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        goal.event_sequence += 1
        event = AgentGoalEventModel(
            goal_id=goal.id,
            sequence=goal.event_sequence,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload=payload,
        )
        self._session.add(event)
        await self._session.flush()
        return event
