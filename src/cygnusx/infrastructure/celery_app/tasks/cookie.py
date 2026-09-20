"""饼干积分定时任务 — 日终对账 + 异常检测"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.cookie.daily_reconcile")
def daily_reconcile() -> dict:
    """日终账本快照 + 异常检测

    每日凌晨 2:30 执行，为所有账户生成当日对账记录并检测异常。
    """
    return asyncio.run(_run_daily_reconcile())


async def _run_daily_reconcile() -> dict:
    from datetime import datetime

    from cygnusx.application.services.cookie_monitor_service import CookieMonitorService
    from cygnusx.infrastructure.database.session import get_session_factory

    snapshot_date = datetime.now().date()
    factory = get_session_factory()
    async with factory() as session:
        try:
            service = CookieMonitorService(session)
            result = await service.reconcile_ledger(snapshot_date)
            await session.commit()

            # 异常告警日志
            for anomaly in result.anomalies:
                if anomaly.severity == "critical":
                    logger.critical(
                        f"[CookieMonitor] {anomaly.anomaly_type}: "
                        f"user={anomaly.user_id} {anomaly.detail}"
                    )
                else:
                    logger.warning(
                        f"[CookieMonitor] {anomaly.anomaly_type}: "
                        f"user={anomaly.user_id} {anomaly.detail}"
                    )

            return {
                "status": "ok",
                "snapshot_date": str(snapshot_date),
                "total_accounts": result.total_accounts,
                "snapshots_created": result.snapshots_created,
                "anomaly_count": len(result.anomalies),
            }
        except Exception as e:
            await session.rollback()
            logger.error(f"[CookieMonitor] 日终对账失败: {e}")
            return {"status": "failed", "error": str(e)}
