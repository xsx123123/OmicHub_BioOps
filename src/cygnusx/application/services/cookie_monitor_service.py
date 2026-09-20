"""饼干积分监控服务 — 余额异常告警 + 流水对账

职责：
1. 日终账本快照 (cookie_ledger) — 对每个账户生成当日快照
2. 异常检测 — 负余额、大额调整、高频消费、冻结账户有活动等
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.cookie.entities import LedgerEntry
from cygnusx.infrastructure.database.models.cookie import (
    CookieAccountModel,
    CookieTransactionModel,
)
from cygnusx.infrastructure.database.repositories.cookie_repository import (
    SqlAlchemyAccountRepository,
    SqlAlchemyLedgerRepository,
)


class AnomalyReport(BaseModel):
    """异常检测报告"""

    anomaly_type: str
    user_id: UUID
    account_id: int | None = None
    username: str = ""
    detail: str = ""
    severity: str = "warning"  # info / warning / critical


class ReconcileResult(BaseModel):
    """对账结果"""

    snapshot_date: date
    total_accounts: int
    snapshots_created: int
    anomalies: list[AnomalyReport] = []


# 异常检测阈值
LARGE_ADJUSTMENT_THRESHOLD = Decimal("50")
HIGH_SPEND_COUNT_THRESHOLD = 20  # 单日消费次数
NEGATIVE_BALANCE_THRESHOLD = Decimal("0")


class CookieMonitorService:
    """饼干积分监控服务"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._account_repo = SqlAlchemyAccountRepository(session)
        self._ledger_repo = SqlAlchemyLedgerRepository(session)

    async def reconcile_ledger(self, snapshot_date: date | None = None) -> ReconcileResult:
        """日终账本快照 — 为每个账户生成当日对账记录

        逻辑：
        1. 查询当日已有快照，已存在则跳过
        2. 查询当日所有交易，聚合 earn/spend/adjust
        3. 取当日首条交易的 balance_after 作为开盘，末条作为收盘
        4. 写入 cookie_ledger
        """
        if snapshot_date is None:
            snapshot_date = datetime.now().date()

        # 查询所有账户
        result = await self._session.execute(
            select(CookieAccountModel).order_by(CookieAccountModel.id)
        )
        accounts = result.scalars().all()
        snapshots_created = 0

        for acct_model in accounts:
            # 幂等：已存在快照则跳过
            existing = await self._ledger_repo.get_by_date_user(snapshot_date, acct_model.user_id)
            if existing is not None:
                continue

            # 聚合当日交易
            day_start = datetime.combine(snapshot_date, datetime.min.time())
            day_end = datetime.combine(snapshot_date + timedelta(days=1), datetime.min.time())

            txn_result = await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(CookieTransactionModel.amount).filter(
                            CookieTransactionModel.txn_type == "earn"
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(func.abs(CookieTransactionModel.amount)).filter(
                            CookieTransactionModel.txn_type == "spend"
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(func.abs(CookieTransactionModel.amount)).filter(
                            CookieTransactionModel.txn_type == "freeze"
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(CookieTransactionModel.amount).filter(
                            CookieTransactionModel.txn_type == "adjust"
                        ),
                        0,
                    ),
                    func.count(CookieTransactionModel.id),
                    func.min(CookieTransactionModel.balance_after),
                    func.max(CookieTransactionModel.balance_after),
                ).where(
                    CookieTransactionModel.user_id == acct_model.user_id,
                    CookieTransactionModel.created_at >= day_start,
                    CookieTransactionModel.created_at < day_end,
                )
            )
            row = txn_result.one()

            # 当日无交易且账户余额为 0 → 跳过（减少噪音）
            txn_count = row[4] or 0
            if txn_count == 0 and (acct_model.balance or 0) == 0:
                continue

            opening_balance = Decimal(str(row[5])) if row[5] is not None else acct_model.balance
            closing_balance = Decimal(str(row[6])) if row[6] is not None else acct_model.balance

            entry = LedgerEntry(
                snapshot_date=snapshot_date,
                user_id=acct_model.user_id,
                account_id=acct_model.id,
                opening_balance=opening_balance,
                total_earned=Decimal(str(row[0] or 0)),
                total_spent=Decimal(str(row[1] or 0)) + Decimal(str(row[2] or 0)),
                total_adjusted=Decimal(str(row[3] or 0)),
                closing_balance=closing_balance,
                transaction_count=txn_count,
            )
            await self._ledger_repo.add(entry)
            snapshots_created += 1

        # 检测异常
        anomalies = await self.detect_anomalies(snapshot_date)

        return ReconcileResult(
            snapshot_date=snapshot_date,
            total_accounts=len(accounts),
            snapshots_created=snapshots_created,
            anomalies=anomalies,
        )

    async def detect_anomalies(self, snapshot_date: date | None = None) -> list[AnomalyReport]:
        """检测余额异常

        检测项：
        1. 负余额 — balance < 0 (critical)
        2. 大额调整 — 单笔 adjust 超过阈值 (warning)
        3. 高频消费 — 单日消费次数超过阈值 (warning)
        4. 冻结账户有活动 — frozen/suspended 账户当日有交易 (warning)
        """
        if snapshot_date is None:
            snapshot_date = datetime.now().date()

        anomalies: list[AnomalyReport] = []
        day_start = datetime.combine(snapshot_date, datetime.min.time())
        day_end = datetime.combine(snapshot_date + timedelta(days=1), datetime.min.time())

        # 1. 负余额检测
        result = await self._session.execute(
            select(CookieAccountModel).where(
                CookieAccountModel.balance < NEGATIVE_BALANCE_THRESHOLD
            )
        )
        for acct in result.scalars().all():
            anomalies.append(
                AnomalyReport(
                    anomaly_type="negative_balance",
                    user_id=acct.user_id,
                    account_id=acct.id,
                    detail=f"账户余额为负: {acct.balance}",
                    severity="critical",
                )
            )

        # 2. 大额调整检测
        result = await self._session.execute(
            select(CookieTransactionModel).where(
                CookieTransactionModel.txn_type == "adjust",
                CookieTransactionModel.created_at >= day_start,
                CookieTransactionModel.created_at < day_end,
                func.abs(CookieTransactionModel.amount) >= LARGE_ADJUSTMENT_THRESHOLD,
            )
        )
        for txn in result.scalars().all():
            anomalies.append(
                AnomalyReport(
                    anomaly_type="large_adjustment",
                    user_id=txn.user_id,
                    detail=f"大额调整 {txn.amount} 🥫: {txn.adjust_reason}",
                    severity="warning",
                )
            )

        # 3. 高频消费检测
        result = await self._session.execute(
            select(
                CookieTransactionModel.user_id,
                func.count(CookieTransactionModel.id).label("txn_count"),
            )
            .where(
                CookieTransactionModel.txn_type.in_(["spend", "freeze"]),
                CookieTransactionModel.created_at >= day_start,
                CookieTransactionModel.created_at < day_end,
            )
            .group_by(CookieTransactionModel.user_id)
        )
        for row in result.all():
            if (row.txn_count or 0) >= HIGH_SPEND_COUNT_THRESHOLD:
                anomalies.append(
                    AnomalyReport(
                        anomaly_type="high_frequency_spend",
                        user_id=row.user_id,
                        detail=f"单日消费 {row.txn_count} 次，超过阈值 {HIGH_SPEND_COUNT_THRESHOLD}",
                        severity="warning",
                    )
                )

        # 4. 冻结账户有活动
        result = await self._session.execute(
            select(CookieTransactionModel)
            .join(
                CookieAccountModel,
                CookieTransactionModel.user_id == CookieAccountModel.user_id,
            )
            .where(
                CookieAccountModel.status.in_(["frozen", "suspended"]),
                CookieTransactionModel.created_at >= day_start,
                CookieTransactionModel.created_at < day_end,
            )
        )
        for txn in result.scalars().all():
            anomalies.append(
                AnomalyReport(
                    anomaly_type="frozen_account_activity",
                    user_id=txn.user_id,
                    detail=f"冻结/停用账户有交易活动: {txn.txn_type} {txn.amount} 🥫",
                    severity="warning",
                )
            )

        return anomalies

    async def get_ledger_report(
        self, snapshot_date: date, offset: int = 0, limit: int = 100
    ) -> list[LedgerEntry]:
        """获取指定日期的账本快照"""
        return await self._ledger_repo.list_by_date(snapshot_date, offset, limit)
