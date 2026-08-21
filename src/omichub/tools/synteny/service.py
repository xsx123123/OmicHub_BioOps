from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.exceptions import NotFoundError, TaskExecutionError, ValidationError
from omichub.domain.task.value_objects import TaskStatus
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.storage import get_path_factory
from omichub.infrastructure.task_queue.dispatcher import enqueue_task
from omichub.tools.synteny.schema import SyntenyBlockDTO, SyntenyPointDTO, SyntenyTaskDTO


class SyntenyService:
    async def submit(
        self,
        db: AsyncSession,
        user_id: str,
        gff3_text: str,
        blastp_text: str,
        chromosome_filter: list[str] | None = None,
        project_name: str = "Synteny",
    ) -> SyntenyTaskDTO:
        genes = self._parse_gff3(gff3_text)
        pairs = self._parse_blast(blastp_text)
        if not genes or not pairs:
            raise ValidationError("GFF3 与 BLASTP outfmt6 均不能为空且必须包含可解析记录")
        if chromosome_filter:
            allowed = set(chromosome_filter)
            pairs = [pair for pair in pairs if pair[0] in genes and pair[1] in genes]
            genes = {key: value for key, value in genes.items() if value[0] in allowed}
        if len(pairs) > 50_000 and not chromosome_filter:
            raise ValidationError("基因对超过 50000，请先按染色体过滤")
        task_id = str(uuid.uuid4())
        work_dir = get_path_factory().create_project_run_dir(user_id, project_name, "synteny")
        await asyncio.to_thread(work_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self._write_input, work_dir, gff3_text, blastp_text)
        task = TaskModel(
            id=uuid.UUID(task_id),
            flow_id="synteny",
            user_id=uuid.UUID(user_id),
            name=project_name,
            status=TaskStatus.QUEUED.value,
            work_dir=str(work_dir),
            progress=0,
            sample_count=0,
            parameters={
                "gene_count": len(genes),
                "pair_count": len(pairs),
                "chromosome_filter": chromosome_filter or [],
            },
        )
        db.add(task)
        await db.commit()
        try:
            from omichub.tools.synteny.tasks import run_synteny_task

            enqueue_task(run_synteny_task, task_id, task_id=task_id)
        except Exception as error:
            task.status, task.error_message = TaskStatus.FAILED.value, str(error)[:2000]
            await db.commit()
            raise TaskExecutionError(task.error_message) from error
        result = self._dto(task)
        result.message = "共线性任务已投递"
        return result

    async def get_task(self, db: AsyncSession, user_id: str, task_id: str) -> SyntenyTaskDTO:
        result = await db.execute(
            select(TaskModel).where(
                TaskModel.id == uuid.UUID(task_id),
                TaskModel.user_id == uuid.UUID(user_id),
                TaskModel.flow_id == "synteny",
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise NotFoundError("找不到共线性任务")
        return self._dto(task)

    @staticmethod
    def _parse_gff3(text: str) -> dict[str, tuple[str, int, int]]:
        genes: dict[str, tuple[str, int, int]] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 9 or fields[2].lower() not in {"gene", "mrna"}:
                continue
            attrs = dict(part.split("=", 1) for part in fields[8].split(";") if "=" in part)
            gene_id = attrs.get("ID") or attrs.get("Parent")
            if gene_id:
                try:
                    genes[gene_id] = (fields[0], int(fields[3]), int(fields[4]))
                except ValueError:
                    continue
        return genes

    @staticmethod
    def _parse_blast(text: str) -> list[tuple[str, str]]:
        result = []
        for line in text.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and fields[0] and fields[1]:
                result.append((fields[0], fields[1]))
        return result

    @staticmethod
    def _write_input(work_dir: Path, gff3: str, blast: str) -> None:
        (work_dir / "input").mkdir(parents=True, exist_ok=True)
        (work_dir / "input" / "annotations.gff3").write_text(gff3, encoding="utf-8")
        (work_dir / "input" / "blastp.outfmt6").write_text(blast, encoding="utf-8")

    @staticmethod
    def _dto(task: TaskModel) -> SyntenyTaskDTO:
        params = task.parameters or {}
        blocks = [SyntenyBlockDTO.model_validate(item) for item in params.get("blocks", [])]
        points = [SyntenyPointDTO.model_validate(item) for item in params.get("points", [])]
        status = {
            TaskStatus.SUCCESS.value: "completed",
            TaskStatus.FAILED.value: "failed",
            TaskStatus.RUNNING.value: "running",
        }.get(task.status, "queued")
        return SyntenyTaskDTO(
            task_id=str(task.id),
            status=status,
            progress=int(task.progress or 0),
            message="共线性任务已投递",
            error_message=task.error_message or None,
            block_count=len(blocks),
            max_block_size=max((b.gene_pairs for b in blocks), default=0),
            chromosome_pairs=list(params.get("chromosome_pairs", [])),
            blocks=blocks,
            points=points,
            result_download_url=f"/api/v1/synteny/tasks/{task.id}/download"
            if status == "completed"
            else None,
            created_at=task.created_at,
            finished_at=task.finished_at,
        )
