"""AI 指标告警定时任务 — 每 5 分钟评估 C4 规则并推送平台通知。

错误率和延迟按短冷却重试；日成本在同一自然日内只推送一次。
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="omichub.infrastructure.celery_app.tasks.ai_metrics.check_alerts")
def check_alerts() -> dict:
    """评估三条规则，超阈值且通过规则对应的去重窗口才推送通知。"""
    return asyncio.run(_run_check_alerts())


async def _run_check_alerts() -> dict:
    from sqlalchemy import select

    from omichub.application.services.ai_metrics_service import AiMetricsService
    from omichub.application.services.notification_service import NotificationService
    from omichub.infrastructure.database.models.user import UserModel
    from omichub.infrastructure.database.repositories.notification_repository import (
        SqlAlchemyNotificationRepository,
    )
    from omichub.infrastructure.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            service = AiMetricsService(session)
            fired = await service.check_and_fire_alerts()
            if not fired:
                await session.commit()
                return {"status": "ok", "fired": 0}

            # 以首个管理员身份发送全局告警通知（created_by 为非空 FK）。
            admin_id = (
                await session.execute(
                    select(UserModel.id).where(UserModel.role == "admin").limit(1)
                )
            ).scalar_one_or_none()
            if admin_id is not None:
                notifier = NotificationService(SqlAlchemyNotificationRepository(session))
                for alert in fired:
                    await notifier.create(
                        created_by=str(admin_id),
                        title="AI 可观测性告警",
                        content=alert["message"],
                        level=alert["level"],
                        is_global=True,
                    )
            await session.commit()
            for alert in fired:
                logger.warning(f"[AiMetrics] {alert['message']}")
            return {"status": "ok", "fired": len(fired)}
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.error(f"[AiMetrics] 告警检查失败: {e}")
            return {"status": "failed", "error": str(e)}
