"""系统发育树构建 Celery 任务。

任务命名：omichub.tools.phylogenetic_tree.tasks.build_tree
路由队列：config.yaml 中 execution.celery.queue（默认 phylo_tree）
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name="omichub.tools.phylogenetic_tree.tasks.build_tree",
    time_limit=3600 * 2,
    soft_time_limit=3600,
    max_retries=1,
    default_retry_delay=30,
    queue="phylo_tree",
)
def build_phylogenetic_tree(self: Any, task_input: dict[str, Any]) -> dict[str, Any]:
    """系统发育树构建主任务：MSA → 树构建 → Bootstrap → 结果格式化。"""
    from omichub.tools.phylogenetic_tree.core import build_tree

    task_id = str(self.request.id)

    def _update_progress(phase: str, progress: float, message: str) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "phase": phase,
                "progress": round(progress, 4),
                "message": message,
                "timestamp": time.time(),
            },
        )

    try:
        return asyncio.run(
            build_tree(task_id, task_input, progress_callback=_update_progress)
        )
    except SoftTimeLimitExceeded:
        return {
            "status": "FAILED",
            "error": "任务执行超时",
            "phases_completed": [],
        }
