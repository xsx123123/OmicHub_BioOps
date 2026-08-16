"""可观测性数据留存定时任务 — 每日清理超期日志/span 归档（C6）"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="omichub.infrastructure.celery_app.tasks.observability.prune_archives")
def prune_archives() -> dict:
    """删除超过冷数据保留天数的日志/span 轮转归档。"""
    from omichub.core.retention import prune_observability_archives

    try:
        return prune_observability_archives()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[Retention] 留存清理失败: {e}")
        return {"status": "failed", "error": str(e)}
