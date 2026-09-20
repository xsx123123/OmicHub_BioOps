from __future__ import annotations

import asyncio
import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery import shared_task

from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.tools.enrichments.config import config_manager
from cygnusx.tools.gsea.runner import GseaDockerRunner, GseaRunParams


@shared_task(
    bind=True, name="cygnusx.tools.gsea.tasks.run_gsea_task", queue="analysis", time_limit=900
)
def run_gsea_task(self: Any, task_id: str) -> dict[str, Any]:
    return asyncio.run(_run(task_id))


async def _run(task_id: str) -> dict[str, Any]:
    async with get_session_factory()() as db:
        task = await db.get(TaskModel, uuid.UUID(task_id))
        if task is None or task.flow_id != "gsea":
            return {"status": "failed", "task_id": task_id}
        task.status, task.progress, task.started_at = (
            TaskStatus.RUNNING.value,
            10,
            datetime.now(UTC),
        )
        await db.commit()
        try:
            input_path = Path(task.work_dir) / "input" / "ranking.tsv"
            output_dir = Path(task.work_dir) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            with input_path.open(encoding="utf-8") as handle:
                ranking = list(csv.DictReader(handle, delimiter="\t"))
            species_id = str((task.parameters or {}).get("species_id") or "")
            species = config_manager.get_species(species_id)
            if species is None or not species.enabled:
                raise RuntimeError(f"物种不可用: {species_id}")
            output_path = output_dir / "gsea_result.csv"
            run_result = await GseaDockerRunner().run(
                GseaRunParams(
                    str(input_path),
                    str(output_path),
                    str((task.parameters or {}).get("gene_set") or "GO_BP"),
                    species.go_annotation,
                    float((task.parameters or {}).get("p_value_cutoff", 0.05)),
                    float((task.parameters or {}).get("q_value_cutoff", 0.1)),
                ),
                f"cygnusx-gsea-{task_id[:8]}",
            )
            if run_result.returncode != 0:
                raise RuntimeError(
                    (run_result.stderr or run_result.stdout or "GSEA R runtime failed")[-2000:]
                )
            top_terms = []
            with output_path.open(encoding="utf-8-sig") as handle:
                for row in list(csv.DictReader(handle))[:10]:
                    top_terms.append(
                        {
                            "id": row["ID"],
                            "description": row["Description"],
                            "nes": float(row["NES"]),
                            "p_adjust": float(row["p.adjust"]),
                            "qvalue": float(row["qvalue"]) if row.get("qvalue") else None,
                        }
                    )
            curve_path = Path(f"{output_path}.running_scores.json")
            curve = (
                json.loads(curve_path.read_text(encoding="utf-8")) if curve_path.exists() else []
            )
            (output_dir / "gsea_manifest.json").write_text(
                json.dumps(
                    {
                        "gene_count": len(ranking),
                        "gene_set": (task.parameters or {}).get("gene_set", ""),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            task.status, task.progress, task.finished_at = (
                TaskStatus.SUCCESS.value,
                100,
                datetime.now(UTC),
            )
            task.parameters = {
                **(task.parameters or {}),
                "top_terms": top_terms,
                "running_score": curve,
                "result_path": str(output_path),
            }
            await db.commit()
            return {"status": "completed", "task_id": task_id}
        except Exception as error:
            task.status, task.progress, task.error_message, task.finished_at = (
                TaskStatus.FAILED.value,
                100,
                str(error)[:2000],
                datetime.now(UTC),
            )
            await db.commit()
            return {"status": "failed", "task_id": task_id}
