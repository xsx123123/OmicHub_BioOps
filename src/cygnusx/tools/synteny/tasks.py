from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from celery import shared_task

from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.tools.synteny.runner import SyntenyDockerRunner


@shared_task(
    bind=True,
    name="cygnusx.tools.synteny.tasks.run_synteny_task",
    queue="analysis",
    time_limit=1800,
)
def run_synteny_task(self: Any, task_id: str) -> dict[str, Any]:
    return asyncio.run(_run(task_id))


async def _run(task_id: str) -> dict[str, Any]:
    async with get_session_factory()() as db:
        task = await db.get(TaskModel, uuid.UUID(task_id))
        if task is None or task.flow_id != "synteny":
            return {"status": "failed", "task_id": task_id}
        task.status = TaskStatus.RUNNING.value
        task.progress = 10
        task.started_at = datetime.now(UTC)
        await db.commit()
        try:
            input_dir = __import__("pathlib").Path(task.work_dir) / "input"
            output_path = __import__("pathlib").Path(task.work_dir) / "output" / "synteny.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            run_result = await SyntenyDockerRunner().run(
                str(input_dir / "annotations.gff3"),
                str(input_dir / "blastp.outfmt6"),
                str(output_path),
                f"cygnusx-synteny-{task_id[:8]}",
            )
            if run_result.returncode != 0:
                raise RuntimeError(
                    (run_result.stderr or run_result.stdout or "synteny runtime failed")[-2000:]
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            blocks = payload.get("blocks", [])
            task.status, task.progress, task.finished_at = (
                TaskStatus.SUCCESS.value,
                100,
                datetime.now(UTC),
            )
            task.parameters = {
                **(task.parameters or {}),
                "blocks": blocks,
                "points": payload.get("points", []),
                "chromosome_pairs": payload.get("chromosome_pairs", []),
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
