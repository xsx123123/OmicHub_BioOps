"""MCP Builder Celery 任务：过期实验 MCP 自动下线.

实验池 MCP 带 TTL（默认 24h），到期后自动置为 offline + 禁用；
容器侧子进程随 Studio 沙箱空闲回收一同销毁，无需额外处理。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.mcp_builder.expire_experimental")
def expire_experimental() -> dict[str, Any]:
    """每 5 分钟扫描并下线过期实验 MCP。"""
    return asyncio.run(_run_expire())


async def _run_expire() -> dict[str, Any]:
    from cygnusx.application.services.mcp_builder_service import MCPBuilderService
    from cygnusx.infrastructure.database.session import get_session_factory

    try:
        async with get_session_factory()() as session:
            service = MCPBuilderService(session)
            count = await service.expire_stale_servers()
            await session.commit()
        if count:
            logger.info("[MCPBuilder] 过期实验 MCP 下线 %s 个", count)
        return {"expired": count}
    except Exception as exc:  # noqa: BLE001
        logger.error("[MCPBuilder] 过期清理失败: %s", exc)
        return {"expired": 0, "error": str(exc)}
