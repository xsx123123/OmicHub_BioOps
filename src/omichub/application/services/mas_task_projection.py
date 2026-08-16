"""Read-only projection of MAS Runs into the existing task-center DTO."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from omichub.application.schemas.task import TaskLogResponse, TaskResponse
from omichub.infrastructure.database.models.mas import MASNodeModel, MASRunModel
from omichub.infrastructure.database.repositories.mas_repository import MASRepository

MAS_TASK_FLOW_ID = "mas"

_RUN_STATUS_MAP = {
    "draft": "pending",
    "awaiting_approval": "pending",
    "queued": "queued",
    "running": "running",
    "paused_for_input": "running",
    "cancelling": "running",
    "succeeded": "success",
    "succeeded_with_warnings": "success",
    "failed": "failed",
    "rejected": "failed",
    "cancelled": "cancelled",
}
_TERMINAL_RUN_STATES = {"succeeded", "succeeded_with_warnings", "failed", "rejected", "cancelled"}
_COMPLETED_NODE_STATES = {"succeeded", "skipped"}


class MASTaskProjection:
    """Adapts durable MAS metadata without creating or mutating legacy Task rows."""

    def __init__(self, repository: MASRepository) -> None:
        self._repository = repository

    async def list_for_user(self, user_id: UUID, status: str | None = None) -> list[TaskResponse]:
        runs = await self._repository.list_runs_for_user(user_id)
        projected = [await self._to_response(run) for run in runs]
        if status:
            projected = [task for task in projected if task.status == status]
        return projected

    async def get_for_user(self, run_id: UUID, user_id: UUID) -> TaskResponse | None:
        run = await self._repository.get_run_for_user(run_id, user_id)
        return await self._to_response(run) if run is not None else None

    async def dag_for_user(self, run_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        run = await self._repository.get_run_for_user(run_id, user_id)
        if run is None:
            return None
        nodes = await self._repository.list_nodes(run.id)
        return {
            "kind": "mas",
            "run_id": str(run.id),
            "status": run.status,
            "nodes": [
                {
                    "id": node.node_key,
                    "label": node.intent,
                    "agent_id": node.agent_id,
                    "status": node.status,
                    "attempt_count": node.attempt_count,
                }
                for node in nodes
            ],
            "edges": [
                {"source": dependency, "target": node.node_key}
                for node in nodes
                for dependency in node.depends_on
            ],
        }

    async def _to_response(self, run: MASRunModel) -> TaskResponse:
        nodes = await self._repository.list_nodes(run.id)
        plan = await self._repository.get_plan_for_run(run.id)
        plan_json = plan.plan_json if plan is not None else {}
        completed_nodes = sum(node.status in _COMPLETED_NODE_STATES for node in nodes)
        progress = completed_nodes / len(nodes) if nodes else 0.0
        mapped_status = _RUN_STATUS_MAP.get(run.status, "pending")
        title = str(plan_json.get("title") or f"MAS 分析计划 {str(run.id)[:8]}")
        error_message = "计划被拒绝" if run.status == "rejected" else ""
        logs = [
            TaskLogResponse(
                timestamp=run.updated_at,
                level="info",
                source="mas",
                message=f"MAS Run 状态：{run.status}；节点完成 {completed_nodes}/{len(nodes)}",
            )
        ]
        return TaskResponse(
            id=run.id,
            flow_id=MAS_TASK_FLOW_ID,
            user_id=run.user_id,
            name=title,
            status=mapped_status,
            execution_mode="mas",
            parameters={
                "mas_run_id": str(run.id),
                "mas_status": run.status,
                "node_count": len(nodes),
                "nodes": [self._node_summary(node) for node in nodes],
                "context_summary": run.context_summary or {},
            },
            work_dir="",
            result_path="",
            error_message=error_message,
            progress=progress,
            logs=logs,
            created_at=run.created_at,
            started_at=run.created_at
            if run.status in {"running", "paused_for_input", "cancelling"}
            else None,
            finished_at=run.finished_at if run.status in _TERMINAL_RUN_STATES else None,
        )

    @staticmethod
    def _node_summary(node: MASNodeModel) -> dict[str, Any]:
        return {
            "key": node.node_key,
            "agent_id": node.agent_id,
            "intent": node.intent,
            "status": node.status,
            "attempt_count": node.attempt_count,
            "depends_on": node.depends_on,
        }
