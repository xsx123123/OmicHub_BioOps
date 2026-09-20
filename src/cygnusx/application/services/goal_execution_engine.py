"""Short-lived autonomous Goal continuation engine.

The engine owns scheduling and leases; it deliberately delegates model/tool execution to
the existing chat service rather than duplicating the Agent runtime.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cygnusx.application.services.goal_evaluator import GoalEvaluator
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.ai_provider.openai_compatible import merge_token_usage
from cygnusx.infrastructure.database.models.goal import (
    AgentGoalEventModel,
    AgentGoalModel,
    AgentGoalWorkUnitModel,
)


@dataclass(frozen=True)
class GoalStepSnapshot:
    goal_id: UUID
    user_id: str
    session_id: str | None
    manager_agent_id: str
    objective: str
    success_criteria: list[Any]
    mode: str
    turn_count: int
    max_turns: int
    plan_snapshot: dict[str, Any]


@dataclass(frozen=True)
class GoalStepResult:
    content: str
    error: str | None = None
    terminal_claim: dict[str, Any] | None = None
    waiting_for_user: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None


class ChatServiceGoalStepExecutor:
    async def execute(self, db: AsyncSession, snapshot: GoalStepSnapshot) -> GoalStepResult:
        from cygnusx.application.services.chat_service import ChatService

        prompt = self._build_prompt(snapshot)
        chunks: list[str] = []
        errors: list[str] = []
        terminal_claim: dict[str, Any] | None = None
        waiting_for_user: dict[str, Any] | None = None
        token_usage: dict[str, Any] | None = None
        goal_fanout_enabled = get_settings().goal_fanout_enabled
        async for chunk in ChatService(db).stream_agent_chat(
            user_id=snapshot.user_id,
            agent_id=snapshot.manager_agent_id,
            messages=[{"role": "user", "content": prompt}],
            session_id=snapshot.session_id,
            mode=snapshot.mode,
            multi_agent=goal_fanout_enabled,
            overdrive=False,
            runtime_context={
                "goal_id": str(snapshot.goal_id),
                "work_unit_key": f"turn-{snapshot.turn_count + 1}",
                "idempotency_key": f"{snapshot.goal_id}:turn:{snapshot.turn_count + 1}",
                "goal_safe_only": True,
                "goal_fanout_enabled": goal_fanout_enabled,
            },
        ):
            if chunk.type == "text" and chunk.content:
                chunks.append(chunk.content)
            elif chunk.type == "error" and chunk.content:
                errors.append(chunk.content)
            elif chunk.type == "tool_result" and chunk.metadata:
                result = chunk.metadata.get("result")
                if (
                    chunk.metadata.get("tool_name") in {"goal_complete", "goal_blocked"}
                    and isinstance(result, dict)
                    and result.get("action") in {"complete", "blocked"}
                ):
                    terminal_claim = result
            elif chunk.type == "ask_request" and chunk.metadata:
                waiting_for_user = dict(chunk.metadata)
            elif chunk.type == "done" and chunk.metadata:
                token_usage = merge_token_usage(token_usage, chunk.metadata.get("usage"))
        return GoalStepResult(
            content="".join(chunks),
            error="\n".join(errors) or None,
            terminal_claim=terminal_claim,
            waiting_for_user=waiting_for_user,
            token_usage=token_usage,
        )

    @staticmethod
    def _build_prompt(snapshot: GoalStepSnapshot) -> str:
        prior = str(snapshot.plan_snapshot.get("last_response") or "")[-6000:]
        answer_packet = snapshot.plan_snapshot.get("latest_user_answer") or {}
        latest_answer = str(answer_packet.get("answer") or "").strip()
        criteria = "\n".join(f"- {item}" for item in snapshot.success_criteria) or "- 完成用户目标"
        return (
            "[GOAL RUNTIME ITERATION]\n"
            f"Goal ID: {snapshot.goal_id}\n"
            f"Iteration: {snapshot.turn_count + 1}/{snapshot.max_turns}\n"
            f"Objective:\n{snapshot.objective}\n\n"
            f"Success criteria:\n{criteria}\n\n"
            f"Previous checkpoint:\n{prior or '(none)'}\n\n"
            f"Latest user answer:\n{latest_answer or '(none)'}\n\n"
            "继续推进目标。先执行当前最有价值且安全的一步；使用现有工具与审批规则。"
            "输出一个简短检查点，包含完成内容、可验证证据、下一步与阻塞项。\n"
            "只有 Goal 真正完成时调用 goal_complete，并为每条成功标准提供 evidence；"
            "无法继续时调用 goal_blocked 并说明最小阻塞原因。不要用自然语言代替终结工具。"
        )


class GoalExecutionEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        step_executor: ChatServiceGoalStepExecutor | None = None,
        lease_seconds: int = 120,
    ) -> None:
        self._session_factory = session_factory
        self._step_executor = step_executor or ChatServiceGoalStepExecutor()
        self._evaluator = GoalEvaluator()
        self._lease_seconds = lease_seconds

    async def run_once(self, goal_id: UUID, cause: str = "continuation") -> bool:
        owner = uuid.uuid4().hex
        from cygnusx.infrastructure.cache.goal_lease import GoalRedisLease

        async with GoalRedisLease(str(goal_id), owner, self._lease_seconds) as lease:
            if not lease.acquired:
                return False
            snapshot = await self._claim(goal_id, owner, cause)
            if snapshot is None:
                return False
            try:
                async with self._session_factory() as db:
                    result = await self._step_executor.execute(db, snapshot)
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                result = GoalStepResult(content="", error=str(exc))
            if lease.lost:
                return False
            return await self._record_result(goal_id, owner, snapshot, result)

    async def _claim(self, goal_id: UUID, owner: str, cause: str) -> GoalStepSnapshot | None:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            goal = (
                await db.execute(select(AgentGoalModel).where(AgentGoalModel.id == goal_id).with_for_update())
            ).scalar_one_or_none()
            if goal is None or goal.status != "in_progress":
                return None
            if goal.deadline_at and goal.deadline_at <= now:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(db, goal, "deadline_exhausted", {})
                await db.commit()
                await self._publish_event(event)
                return None
            if goal.turn_count >= goal.max_turns:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db, goal, "budget_exhausted", {"max_turns": goal.max_turns}
                )
                await db.commit()
                await self._publish_event(event)
                return None
            if goal.token_budget is not None and goal.tokens_used >= goal.token_budget:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db,
                    goal,
                    "token_budget_exhausted",
                    {"token_budget": goal.token_budget, "tokens_used": goal.tokens_used},
                )
                await db.commit()
                await self._publish_event(event)
                return None
            if goal.lease_expires_at and goal.lease_expires_at > now:
                return None
            goal.lease_owner = owner
            goal.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            goal.version += 1
            event = await self._append_event(db, goal, "continued", {"cause": cause})
            await db.commit()
            await self._publish_event(event)
            return GoalStepSnapshot(
                goal_id=goal.id,
                user_id=str(goal.user_id),
                session_id=goal.session_id,
                manager_agent_id=goal.manager_agent_id,
                objective=goal.objective,
                success_criteria=goal.success_criteria,
                mode=goal.mode,
                turn_count=goal.turn_count,
                max_turns=goal.max_turns,
                plan_snapshot=dict(goal.plan_snapshot or {}),
            )

    async def _record_result(
        self, goal_id: UUID, owner: str, snapshot: GoalStepSnapshot, result: GoalStepResult
    ) -> bool:
        async with self._session_factory() as db:
            goal = (
                await db.execute(select(AgentGoalModel).where(AgentGoalModel.id == goal_id).with_for_update())
            ).scalar_one_or_none()
            if goal is None or goal.status != "in_progress" or goal.lease_owner != owner:
                return False
            now = datetime.now(UTC)
            step_tokens = self._token_total(result.token_usage)
            unit = AgentGoalWorkUnitModel(
                goal_id=goal.id,
                work_unit_key=f"turn-{goal.turn_count + 1}",
                kind="llm_step",
                title=f"Goal iteration {goal.turn_count + 1}",
                instruction=goal.objective,
                owner_agent_id=goal.manager_agent_id,
                status="failed" if result.error else "succeeded",
                attempt=1,
                output_ref={
                    "content": result.content[-12000:],
                    "error": result.error,
                    "token_usage": result.token_usage,
                },
                evidence_refs=[],
                idempotency_key=f"{goal.id}:turn:{goal.turn_count + 1}",
                started_at=now,
                finished_at=now,
            )
            db.add(unit)
            goal.turn_count += 1
            goal.tokens_used += step_tokens
            goal.version += 1
            goal.lease_owner = None
            goal.lease_expires_at = None
            goal.plan_snapshot = {
                **dict(goal.plan_snapshot or {}),
                "last_response": result.content[-12000:],
            }
            goal.plan_snapshot.pop("latest_user_answer", None)
            if result.error:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(db, goal, "step_failed", {"error": result.error})
                should_continue = False
            elif result.waiting_for_user:
                goal.status = "waiting_user"
                goal.plan_snapshot["pending_user_request"] = result.waiting_for_user
                event = await self._append_event(
                    db,
                    goal,
                    "waiting_user",
                    {"turn": goal.turn_count, "request": result.waiting_for_user},
                )
                should_continue = False
            elif result.terminal_claim and result.terminal_claim["action"] == "complete":
                goal.status = "completed"
                goal.completed_at = now
                event = await self._append_event(
                    db,
                    goal,
                    "completed",
                    {
                        "evidence": result.terminal_claim.get("evidence") or [],
                        "reason": result.terminal_claim.get("reason") or "",
                    },
                )
                should_continue = False
            elif result.terminal_claim and result.terminal_claim["action"] == "blocked":
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db,
                    goal,
                    "blocked",
                    {"reason": result.terminal_claim.get("reason") or ""},
                )
                should_continue = False
            elif (evaluation := self._evaluator.evaluate(goal.success_criteria, result.content)).action == "complete":
                goal.status = "completed"
                goal.completed_at = now
                event = await self._append_event(
                    db,
                    goal,
                    "completed",
                    {"evidence": evaluation.evidence, "reason": evaluation.reason},
                )
                should_continue = False
            elif evaluation.action == "blocked":
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db, goal, "blocked", {"reason": evaluation.reason}
                )
                should_continue = False
            elif goal.turn_count >= goal.max_turns:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db, goal, "budget_exhausted", {"max_turns": goal.max_turns}
                )
                should_continue = False
            elif goal.token_budget is not None and goal.tokens_used >= goal.token_budget:
                goal.status = "blocked"
                goal.completed_at = now
                event = await self._append_event(
                    db,
                    goal,
                    "token_budget_exhausted",
                    {
                        "token_budget": goal.token_budget,
                        "tokens_used": goal.tokens_used,
                        "step_tokens": step_tokens,
                    },
                )
                should_continue = False
            else:
                event = await self._append_event(
                    db,
                    goal,
                    "step_finished",
                    {
                        "turn": goal.turn_count,
                        "content": result.content[-4000:],
                        "step_tokens": step_tokens,
                        "tokens_used": goal.tokens_used,
                    },
                )
                should_continue = True
            await db.commit()
        await self._publish_event(event)
        return should_continue

    async def recover_expired_leases(self, limit: int = 100) -> list[UUID]:
        now = datetime.now(UTC)
        recovered: list[UUID] = []
        events: list[AgentGoalEventModel] = []
        async with self._session_factory() as db:
            goals = list(
                (
                    await db.execute(
                        select(AgentGoalModel)
                        .where(
                            AgentGoalModel.status == "in_progress",
                            AgentGoalModel.lease_expires_at.is_not(None),
                            AgentGoalModel.lease_expires_at <= now,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(limit)
                    )
                ).scalars()
            )
            for goal in goals:
                previous_owner = goal.lease_owner or "unknown"
                previous_expiry = goal.lease_expires_at.isoformat() if goal.lease_expires_at else "unknown"
                goal.lease_owner = None
                goal.lease_expires_at = None
                goal.version += 1
                event = await self._append_event(
                    db,
                    goal,
                    "lease_recovered",
                    {"previous_owner": previous_owner, "previous_expiry": previous_expiry},
                    dedupe_key=f"lease_recovered:{previous_owner}:{previous_expiry}",
                )
                recovered.append(goal.id)
                events.append(event)
            await db.commit()
        for event in events:
            await self._publish_event(event)
        return recovered

    @staticmethod
    def _token_total(usage: dict[str, Any] | None) -> int:
        if not usage:
            return 0
        try:
            return max(0, int(usage.get("total_tokens") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    async def _append_event(
        db: AsyncSession,
        goal: AgentGoalModel,
        event_type: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str | None = None,
    ) -> AgentGoalEventModel:
        if dedupe_key:
            existing = (
                await db.execute(
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
        db.add(event)
        await db.flush()
        return event

    @staticmethod
    async def _publish_event(event: AgentGoalEventModel) -> None:
        from cygnusx.infrastructure.cache.goal_pubsub import publish_goal_event

        try:
            await publish_goal_event(
                str(event.goal_id),
                {
                    "id": str(event.id),
                    "goal_id": str(event.goal_id),
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "dedupe_key": event.dedupe_key,
                    "payload": event.payload,
                    "created_at": event.created_at,
                },
            )
        except Exception:  # noqa: BLE001
            # Event rows are already committed. A subscriber can recover them by cursor.
            return
