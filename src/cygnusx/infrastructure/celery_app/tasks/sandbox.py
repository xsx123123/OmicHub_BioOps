"""沙盒定时任务 - 超时会话回收"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.sandbox.recycle_expired")
def recycle_expired() -> dict[str, Any]:
    """每分钟扫描并回收无活动超过 5 分钟的轻量沙盒会话。"""
    return asyncio.run(_run_recycle())


async def _run_recycle() -> dict[str, Any]:
    from cygnusx.application.services.sandbox_service import SandboxService
    from cygnusx.infrastructure.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            service = SandboxService(session)
            count = await service.recycle_expired()
            await session.commit()
            logger.info(f"[Sandbox] 回收超时会话 {count} 个")
            return {"recycled": count}
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.error(f"[Sandbox] 回收失败: {e}")
            return {"recycled": 0, "error": str(e)}
