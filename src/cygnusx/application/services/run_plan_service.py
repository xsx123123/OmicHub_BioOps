"""Application service for the Snakemake Run plan confirmation boundary."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.run_plan import SnakemakePlanSubmit, SnakemakePlanView
from cygnusx.application.schemas.task import TaskSubmitRequest
from cygnusx.application.services.flow_service import FlowService
from cygnusx.application.services.task_service import TaskService
from cygnusx.core.exceptions import ConflictError, NotFoundError, ValidationError
from cygnusx.domain.task.value_objects import ExecutionMode
from cygnusx.infrastructure.database.models.run import RunModel
from cygnusx.infrastructure.database.models.run_event import RunEventModel
from cygnusx.infrastructure.database.models.file import FileRecordModel


class RunPlanService:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._flows = FlowService()

    async def submit(self, user_id: UUID, req: SnakemakePlanSubmit) -> SnakemakePlanView:
        flow = self._flows.get_flow(req.flow_id)
        if flow.meta.version != req.release_id:
            raise ValidationError(
                f"release_id={req.release_id!r} 与 flow {req.flow_id!r} 的当前版本不匹配"
            )
        plan = req.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self._db.scalar(
            select(RunModel).where(
                RunModel.user_id == user_id, RunModel.request_key == req.request_key
            )
        )
        if existing:
            if existing.plan_digest != digest:
                raise ConflictError("request_key 已被不同计划占用")
            return self._view(existing)
        run = RunModel(
            user_id=user_id,
            project_slug=req.project_slug,
            flow_id=req.flow_id,
            release_id=req.release_id,
            request_key=req.request_key,
            plan_json=plan,
            plan_digest=digest,
            status="plan_pending",
        )
        self._db.add(run)
        await self._db.flush()
        from cygnusx.application.services.run_event_service import RunEventService

        await RunEventService(self._db).emit(run.id, status="plan_pending")
        return self._view(run)

    async def get(self, user_id: UUID, run_id: UUID) -> SnakemakePlanView:
        run = await self._db.scalar(
            select(RunModel).where(RunModel.id == run_id, RunModel.user_id == user_id)
        )
        if run is None:
            raise NotFoundError("Run 不存在")
        return self._view(run)

    async def list_runs(self, user_id: UUID, project_slug: str | None = None, status: str | None = None):
        query = select(RunModel).where(RunModel.user_id == user_id)
        if project_slug:
            query = query.where(RunModel.project_slug == project_slug)
        if status:
            query = query.where(RunModel.status == status)
        result = await self._db.scalars(query.order_by(RunModel.created_at.desc()).limit(100))
        return [self._view(run) for run in result.all()]

    async def confirm(self, user_id: UUID, run_id: UUID, user_confirmed: bool) -> SnakemakePlanView:
        run = await self._db.scalar(
            select(RunModel).where(RunModel.id == run_id, RunModel.user_id == user_id)
        )
        if run is None:
            raise NotFoundError("Run 不存在")
        if not user_confirmed:
            raise ValidationError("必须明确提供真实用户确认")
        if run.status == "queued":
            return self._view(run)
        if run.status != "plan_pending":
            raise ConflictError(f"Run 当前状态 {run.status!r} 不允许确认")
        payload = run.plan_json
        task = await TaskService(self._db).submit(
            str(user_id),
            TaskSubmitRequest(
                flow_id=run.flow_id,
                name=payload["name"],
                parameters=payload.get("parameters", {}),
                sample_sheet=payload.get("sample_sheet", []),
                comparisons=payload.get("comparisons", []),
                execution_mode=ExecutionMode.LOCAL,
                idempotency_key=f"run:{run.id}",
            ),
        )
        run.task_id = task.id
        run.status = "queued"
        run.confirmed_at = datetime.now(timezone.utc)
        from cygnusx.application.services.run_event_service import RunEventService

        await RunEventService(self._db).emit(run.id, task_id=task.id, status="queued")
        await self._db.flush()
        return self._view(run)

    async def events(self, user_id: UUID, run_id: UUID, limit: int = 200) -> list[dict]:
        run = await self._db.scalar(
            select(RunModel).where(RunModel.id == run_id, RunModel.user_id == user_id)
        )
        if run is None:
            raise NotFoundError("Run 不存在")
        rows = await self._db.scalars(
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id)
            .order_by(RunEventModel.sequence.asc())
            .limit(max(1, min(limit, 500)))
        )
        return [
            {
                "event_id": str(event.id),
                "run_id": str(event.run_id),
                "task_id": str(event.task_id) if event.task_id else None,
                "status": event.status,
                "phase": event.phase,
                "progress": event.progress,
                "rule": event.rule,
                "sequence": event.sequence,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload,
            }
            for event in rows.all()
        ]

    async def artifacts(self, user_id: UUID, run_id: UUID) -> list[dict]:
        run = await self._db.scalar(
            select(RunModel).where(RunModel.id == run_id, RunModel.user_id == user_id)
        )
        if run is None:
            raise NotFoundError("Run 不存在")
        if run.task_id is None:
            return []
        rows = await self._db.scalars(
            select(FileRecordModel).where(
                FileRecordModel.task_id == run.task_id, FileRecordModel.user_id == user_id
            )
        )
        return [
            {
                "artifact_id": str(file.id),
                "name": file.original_name,
                "path": file.storage_path,
                "size": file.size,
                "checksum": file.checksum,
                "status": file.status,
            }
            for file in rows.all()
        ]

    @staticmethod
    def _view(run: RunModel) -> SnakemakePlanView:
        return SnakemakePlanView(
            run_id=run.id,
            project_slug=run.project_slug,
            flow_id=run.flow_id,
            release_id=run.release_id,
            name=run.plan_json.get("name", ""),
            status=run.status,
            plan_digest=run.plan_digest,
            task_id=run.task_id,
            created_at=run.created_at,
        )
