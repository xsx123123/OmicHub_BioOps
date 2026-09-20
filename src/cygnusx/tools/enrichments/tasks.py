"""GO / KEGG 富集 Celery 任务。

Web 进程只创建 ``tasks`` 记录并投递本任务；R Docker 容器仅由独立计算 Worker 启动。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery import shared_task

from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.tools.enrichments.config import config_manager
from cygnusx.tools.enrichments.runner import EnrichmentDockerRunner, EnrichmentRunParams
from cygnusx.tools.enrichments.schema import EnrichmentResultDTO
from cygnusx.tools.enrichments.service import EnrichmentService

logger = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name="cygnusx.tools.enrichments.tasks.run_enrichment_task",
    queue="analysis",
    time_limit=900,
    soft_time_limit=840,
)
def run_enrichment_task(self: Any, task_id: str) -> dict[str, Any]:
    """在计算 Worker 中运行 R Docker，并将可序列化结果写回通用任务表。"""
    return asyncio.run(_run_enrichment(task_id))


async def _run_enrichment(task_id: str) -> dict[str, Any]:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return {"status": "failed", "task_id": task_id, "error": "非法富集任务 ID"}

    factory = get_session_factory()
    async with factory() as db:
        task = await db.get(TaskModel, task_uuid)
        if task is None or task.flow_id != "kegg-enrichment":
            return {"status": "failed", "task_id": task_id, "error": "富集任务不存在"}
        if task.status == TaskStatus.CANCELLED.value:
            return {"status": "cancelled", "task_id": task_id}

        task.status = TaskStatus.RUNNING.value
        task.progress = 10
        task.started_at = datetime.now(UTC)
        task.error_message = ""
        await db.commit()

        try:
            species_id = str((task.parameters or {}).get("species_id") or "")
            species = config_manager.get_species(species_id)
            if species is None or not species.enabled:
                raise RuntimeError(f"物种不可用: {species_id or '未指定'}")

            work_dir = Path(task.work_dir)
            input_path = work_dir / "input" / "gene_list.txt"
            if not input_path.exists():
                input_path = work_dir / "gene_list.txt"
            output_path = work_dir / "output" / "enrichment_result.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not input_path.exists():
                raise RuntimeError("任务输入基因列表不存在")

            task_parameters = task.parameters or {}
            p_value_cutoff = float(
                task_parameters.get("p_value_cutoff", species.p_value_cutoff)
            )
            q_value_cutoff = float(
                task_parameters.get("q_value_cutoff", species.q_value_cutoff)
            )

            params = EnrichmentRunParams(
                input_path=str(input_path),
                output_path=str(output_path),
                kegg_code=species.kegg_code,
                id_type=species.id_type,
                go_obo=species.go_obo,
                go_annotation=species.go_annotation,
                kegg_id_map=species.kegg_id_map,
                kegg_key_type=species.kegg_key_type,
                p_value_cutoff=p_value_cutoff,
                q_value_cutoff=q_value_cutoff,
            )
            container_name = f"cygnusx-enrich-{task_id[:8]}"
            run_result = await EnrichmentDockerRunner().run(params, container_name)
            if run_result.returncode != 0:
                detail = run_result.stderr.strip() or run_result.stdout.strip()
                raise RuntimeError(detail[-2000:] or f"R 容器退出码: {run_result.returncode}")

            rows = EnrichmentService._read_result_csv(output_path)
            result = EnrichmentResultDTO(
                task_id=task_id,
                table_data=rows,
            )
            task.status = TaskStatus.SUCCESS.value
            task.progress = 100
            task.finished_at = datetime.now(UTC)
            task.result_path = str(output_path)
            task.parameters = {**(task.parameters or {}), "result": result.model_dump(mode="json")}
            await db.commit()
            return {"status": "completed", "task_id": task_id}
        except Exception as error:  # noqa: BLE001
            logger.exception("富集任务失败: %s", task_id)
            task.status = TaskStatus.FAILED.value
            task.progress = 100
            task.finished_at = datetime.now(UTC)
            task.error_message = str(error)[:2000]
            await db.commit()
            return {"status": "failed", "task_id": task_id, "error": task.error_message}
