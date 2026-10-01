"""Durable Run event writer used by executors and projections."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.run import RunModel
from cygnusx.infrastructure.database.models.run_event import RunEventModel


class RunEventService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def emit(
        self,
        run_id: UUID,
        *,
        status: str,
        task_id: UUID | None = None,
        phase: str = "task",
        progress: float = 0.0,
        rule: str | None = None,
        payload: dict | None = None,
    ) -> RunEventModel | None:
        run = await self._db.scalar(select(RunModel).where(RunModel.id == run_id))
        if run is None:
            return None
        last = await self._db.scalar(
            select(func.max(RunEventModel.sequence)).where(RunEventModel.run_id == run_id)
        )
        event = RunEventModel(
            run_id=run_id,
            task_id=task_id,
            project_slug=run.project_slug,
            executor="snakemake",
            status=status,
            phase=phase,
            progress=max(0.0, min(1.0, progress)),
            rule=rule,
            payload=payload or {},
            sequence=int(last or 0) + 1,
            occurred_at=datetime.now(timezone.utc),
        )
        self._db.add(event)
        await self._db.flush()
        return event
