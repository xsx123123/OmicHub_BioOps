"""Persisted Goal adapter for the existing parallel subagent executor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.parallel_subagent_tool_service import ParallelSubAgentToolService
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.goal import (
    AgentGoalEventModel,
    AgentGoalModel,
    AgentGoalWorkUnitModel,
)
from omichub.infrastructure.database.session import get_session_factory


class GoalFanoutAdapter:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        fanout_service: ParallelSubAgentToolService | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._fanout_service = fanout_service or ParallelSubAgentToolService()

    async def execute(
        self,
        *,
        context_summary: str,
        tasks: list[dict[str, Any]],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        goal_id = self._goal_id(context)
        parent_key = f"{context.extra.get('work_unit_key') or 'goal'}:fanout"
        normalized_tasks = [
            {**task, "task_id": str(task.get("task_id") or f"{parent_key}:worker:{index}")}
            for index, task in enumerate(tasks, start=1)
        ]
        cached = await self._start_units(goal_id, parent_key, normalized_tasks, context)
        if cached is not None:
            return cached
        envelope = await self._fanout_service.run_parallel_subagents(
            context_summary=context_summary,
            tasks=normalized_tasks,
            context=context,
        )
        await self._finish_units(goal_id, parent_key, normalized_tasks, envelope)
        return envelope

    async def _start_units(
        self,
        goal_id: UUID,
        parent_key: str,
        tasks: list[dict[str, Any]],
        context: ToolInvocationContext,
    ) -> dict[str, Any] | None:
        async with self._session_factory() as db:
            goal = await self._goal_for_update(db, goal_id, context.user_id)
            parent = await self._unit(db, goal_id, parent_key)
            if parent and parent.status == "succeeded":
                envelope = (parent.output_ref or {}).get("envelope")
                if isinstance(envelope, dict):
                    return envelope
            if parent is None:
                parent = AgentGoalWorkUnitModel(
                    goal_id=goal_id,
                    work_unit_key=parent_key,
                    kind="parallel_fanout",
                    title="Parallel subagent fan-out",
                    instruction="Run independent Goal worker tasks",
                    owner_agent_id=context.agent_id,
                    idempotency_key=f"{goal_id}:{parent_key}",
                    input_ref={"tasks": tasks},
                    status="running",
                    attempt=1,
                    started_at=datetime.now(UTC),
                )
                db.add(parent)
            else:
                parent.status = "running"
                parent.attempt += 1
                parent.started_at = datetime.now(UTC)
            for task in tasks:
                task_key = str(task["task_id"])
                unit = await self._unit(db, goal_id, task_key)
                if unit is None:
                    db.add(
                        AgentGoalWorkUnitModel(
                            goal_id=goal_id,
                            work_unit_key=task_key,
                            kind="parallel_worker",
                            title=f"Worker: {task.get('agent_id') or ''}",
                            instruction=str(task.get("task") or ""),
                            owner_agent_id=str(task.get("agent_id") or ""),
                            idempotency_key=f"{goal_id}:{task_key}",
                            input_ref={"task": task},
                            status="running",
                            attempt=1,
                            started_at=datetime.now(UTC),
                        )
                    )
                elif unit.status != "succeeded":
                    unit.status = "running"
                    unit.attempt += 1
                    unit.started_at = datetime.now(UTC)
            event = self._append_event(
                goal,
                "fanout_started",
                {"work_unit_key": parent_key, "tasks": normalized_task_view(tasks)},
            )
            db.add(event)
            await db.commit()
        await self._publish(event)
        return None

    async def _finish_units(
        self,
        goal_id: UUID,
        parent_key: str,
        tasks: list[dict[str, Any]],
        envelope: dict[str, Any],
    ) -> None:
        results = list((envelope.get("llm_payload") or {}).get("results") or [])
        results_by_task = {str(item.get("task_id") or ""): item for item in results}
        events: list[AgentGoalEventModel] = []
        async with self._session_factory() as db:
            goal = (
                await db.execute(
                    select(AgentGoalModel).where(AgentGoalModel.id == goal_id).with_for_update()
                )
            ).scalar_one()
            for task in tasks:
                task_key = str(task["task_id"])
                unit = await self._unit(db, goal_id, task_key)
                if unit is None:
                    continue
                result = results_by_task.get(task_key) or {}
                unit.status = self._unit_status(str(result.get("status") or "failed"))
                unit.output_ref = {"result": result}
                unit.evidence_refs = self._evidence_refs(result)
                unit.finished_at = datetime.now(UTC)
                event = self._append_event(
                    goal,
                    "worker_result",
                    {
                        "work_unit_key": task_key,
                        "status": unit.status,
                        "agent_id": unit.owner_agent_id,
                        "evidence_refs": unit.evidence_refs,
                    },
                )
                db.add(event)
                events.append(event)
            parent = await self._unit(db, goal_id, parent_key)
            if parent is not None:
                parent.status = "succeeded" if envelope.get("success") else "failed"
                parent.output_ref = {"envelope": envelope}
                parent.finished_at = datetime.now(UTC)
            event = self._append_event(
                goal,
                "fanout_finished",
                {
                    "work_unit_key": parent_key,
                    "success": bool(envelope.get("success")),
                    "summary": str((envelope.get("llm_payload") or {}).get("summary") or ""),
                },
            )
            db.add(event)
            events.append(event)
            await db.commit()
        for event in events:
            await self._publish(event)

    @staticmethod
    def _goal_id(context: ToolInvocationContext) -> UUID:
        try:
            return UUID(str(context.extra.get("goal_id") or ""))
        except ValueError as exc:
            raise BusinessError("Goal fan-out 缺少有效 goal_id") from exc

    @staticmethod
    async def _goal_for_update(db: AsyncSession, goal_id: UUID, user_id: str) -> AgentGoalModel:
        goal = (
            await db.execute(
                select(AgentGoalModel).where(
                    AgentGoalModel.id == goal_id,
                    AgentGoalModel.user_id == UUID(user_id),
                    AgentGoalModel.status == "in_progress",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if goal is None:
            raise BusinessError("Goal 不存在、已终结或无权执行 fan-out")
        return goal

    @staticmethod
    async def _unit(
        db: AsyncSession, goal_id: UUID, work_unit_key: str
    ) -> AgentGoalWorkUnitModel | None:
        return (
            await db.execute(
                select(AgentGoalWorkUnitModel).where(
                    AgentGoalWorkUnitModel.goal_id == goal_id,
                    AgentGoalWorkUnitModel.work_unit_key == work_unit_key,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    def _append_event(
        goal: AgentGoalModel, event_type: str, payload: dict[str, Any]
    ) -> AgentGoalEventModel:
        goal.event_sequence += 1
        return AgentGoalEventModel(
            goal_id=goal.id,
            sequence=goal.event_sequence,
            event_type=event_type,
            payload=payload,
        )

    @staticmethod
    def _unit_status(status: str) -> str:
        return {
            "ok": "succeeded",
            "awaiting_input": "waiting",
            "approval_pending": "waiting",
            "timeout": "failed",
            "failed": "failed",
        }.get(status, "failed")

    @staticmethod
    def _evidence_refs(result: dict[str, Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        if result.get("answer"):
            evidence.append({"type": "worker_answer", "value": str(result["answer"])[:12000]})
        if result.get("workdir"):
            evidence.append({"type": "workspace", "path": str(result["workdir"])})
        return evidence

    @staticmethod
    async def _publish(event: AgentGoalEventModel) -> None:
        from omichub.infrastructure.cache.goal_pubsub import publish_goal_event

        try:
            await publish_goal_event(
                str(event.goal_id),
                {
                    "id": str(event.id),
                    "goal_id": str(event.goal_id),
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at,
                },
            )
        except Exception:  # noqa: BLE001
            return


def normalized_task_view(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "task_id": str(task.get("task_id") or ""),
            "agent_id": str(task.get("agent_id") or ""),
            "task": str(task.get("task") or "")[:500],
        }
        for task in tasks
    ]
