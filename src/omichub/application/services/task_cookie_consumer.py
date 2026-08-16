"""饼干积分消费者 — 任务生命周期集成

集成点#2: 任务提交前预估+预扣
集成点#3: 任务完成时结算 (多退少补)
集成点#4: 任务取消退还预扣饼干
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.cookie_service import CookieService, PricingEngine
from omichub.core.config import get_settings


class TaskCookieConsumer:
    """任务饼干消费者 — 在任务生命周期中管理饼干扣费"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._cookie_service = CookieService(session)
        self._pricing_engine = PricingEngine(session)
        self._settings = get_settings()

    async def on_submit(
        self,
        user_id: UUID,
        task_id: str,
        flow_id: str,
        sample_count: int = 0,
        comparison_count: int = 0,
    ) -> Decimal:
        """集成点#2: 任务提交前预估+预扣

        Returns:
            pre_deducted_amount: 预扣的饼干数（用于后续结算）
        """
        if not self._settings.enable_cookie_system:
            return Decimal("0")

        estimated = await self._pricing_engine.estimate_task_cost(
            flow_id, sample_count, comparison_count
        )
        await self._cookie_service.pre_deduct(
            user_id=user_id,
            amount=estimated,
            source_type="task",
            source_id=task_id,
            description=f"任务提交预扣 {estimated} 🥫 (flow={flow_id}, samples={sample_count}, comparisons={comparison_count})",
        )
        return estimated

    async def on_complete(
        self,
        user_id: UUID,
        task_id: str,
        flow_id: str,
        pre_deducted: Decimal,
        sample_count: int = 0,
        comparison_count: int = 0,
        execution_seconds: int | None = None,
        resource_cores: int | None = None,
    ) -> None:
        """集成点#3: 任务完成时结算 (多退少补)"""
        if not self._settings.enable_cookie_system or pre_deducted == 0:
            return

        actual_cost = await self._pricing_engine.estimate_task_cost(
            flow_id, sample_count, comparison_count
        )
        await self._cookie_service.settle(
            user_id=user_id,
            pre_deducted=pre_deducted,
            actual_cost=actual_cost,
            source_type="task",
            source_id=task_id,
            task_type=flow_id,
            resource_cores=resource_cores,
            execution_seconds=execution_seconds,
        )

    async def on_cancel(self, user_id: UUID, task_id: str, pre_deducted: Decimal) -> None:
        """集成点#4: 任务取消退还预扣饼干"""
        if not self._settings.enable_cookie_system or pre_deducted == 0:
            return

        await self._cookie_service.refund(
            user_id=user_id,
            amount=pre_deducted,
            source_type="task",
            source_id=task_id,
            description=f"任务取消退还预扣 {pre_deducted} 🥫",
        )
