from __future__ import annotations

import asyncio
import csv
import io
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import NotFoundError, TaskExecutionError, ValidationError
from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.storage import get_path_factory
from cygnusx.infrastructure.storage.path_factory import project_slug
from cygnusx.infrastructure.task_queue.dispatcher import enqueue_task
from cygnusx.tools.gsea.schema import GseaTaskDTO, GseaTermDTO


class GseaService:
    async def submit(
        self,
        db: AsyncSession,
        user_id: str,
        gene_ranking: str,
        species_id: str,
        gene_set: str,
        project_name: str = "GSEA",
        p_value_cutoff: float = 0.05,
        q_value_cutoff: float = 0.1,
        **_: object,
    ) -> GseaTaskDTO:
        rows = self._parse_ranking(gene_ranking)
        if len(rows) < 10:
            raise ValidationError("排序基因列表至少需要 10 个 gene_id + score 条目")
        task_id = str(uuid.uuid4())
        work_dir = get_path_factory().create_project_run_dir(user_id, project_name, "gsea")
        await asyncio.to_thread(work_dir.mkdir, parents=True, exist_ok=True)
        input_path = work_dir / "input" / "ranking.tsv"
        await asyncio.to_thread(self._write_ranking, input_path, rows)
        task = TaskModel(
            id=uuid.UUID(task_id),
            flow_id="gsea",
            user_id=uuid.UUID(user_id),
            name=project_name,
            status=TaskStatus.QUEUED.value,
            work_dir=str(work_dir),
            progress=0,
            sample_count=0,
            parameters={
                "species_id": species_id,
                "gene_set": gene_set,
                "gene_count": len(rows),
                "project_slug": project_slug(project_name, fallback="gsea"),
                "p_value_cutoff": p_value_cutoff,
                "q_value_cutoff": q_value_cutoff,
            },
        )
        db.add(task)
        await db.commit()
        try:
            from cygnusx.tools.gsea.tasks import run_gsea_task

            enqueue_task(run_gsea_task, task_id, task_id=task_id)
        except Exception as error:
            task.status = TaskStatus.FAILED.value
            task.error_message = str(error)[:2000]
            await db.commit()
            raise TaskExecutionError(task.error_message) from error
        result = self._dto(task)
        result.message = "GSEA 任务已投递"
        return result

    async def get_task(self, db: AsyncSession, user_id: str, task_id: str) -> GseaTaskDTO:
        result = await db.execute(
            select(TaskModel).where(
                TaskModel.id == uuid.UUID(task_id),
                TaskModel.user_id == uuid.UUID(user_id),
                TaskModel.flow_id == "gsea",
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise NotFoundError("找不到 GSEA 任务")
        return self._dto(task)

    @staticmethod
    def _parse_ranking(value: str) -> list[tuple[str, float]]:
        reader = csv.reader(
            io.StringIO(value), delimiter="\t" if "\t" in value.splitlines()[0] else ","
        )
        rows = list(reader)
        if rows and rows[0][0].lower() in {"gene_id", "gene", "id"}:
            rows = rows[1:]
        try:
            return [
                (row[0].strip(), float(row[1])) for row in rows if len(row) >= 2 and row[0].strip()
            ]
        except ValueError as error:
            raise ValidationError("score 列必须为数值") from error

    @staticmethod
    def _write_ranking(path: Path, rows: list[tuple[str, float]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["gene_id", "score"])
            writer.writerows(rows)

    @staticmethod
    def _dto(task: TaskModel) -> GseaTaskDTO:
        status = {
            TaskStatus.SUCCESS.value: "completed",
            TaskStatus.FAILED.value: "failed",
            TaskStatus.RUNNING.value: "running",
        }.get(task.status, "queued")
        terms = [
            GseaTermDTO.model_validate(item)
            for item in (task.parameters or {}).get("top_terms", [])
        ]
        return GseaTaskDTO(
            task_id=str(task.id),
            status=status,
            progress=int(task.progress or 0),
            message="GSEA 任务已投递" if status == "queued" else "GSEA 任务状态已更新",
            error_message=task.error_message or None,
            project_name=task.name or "",
            species_id=str((task.parameters or {}).get("species_id", "")),
            gene_set=str((task.parameters or {}).get("gene_set", "")),
            gene_count=int((task.parameters or {}).get("gene_count", 0)),
            top_terms=terms,
            running_score=list((task.parameters or {}).get("running_score", [])),
            result_download_url=f"/api/v1/gsea/tasks/{task.id}/download"
            if status == "completed"
            else None,
            created_at=task.created_at,
            finished_at=task.finished_at,
        )
