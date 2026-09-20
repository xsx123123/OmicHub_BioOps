"""饼干积分仓储实现 — SQLAlchemy"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.cookie.entities import (
    ConsumptionLog,
    CookieAccount,
    CookiePricing,
    CookieTransaction,
    LedgerEntry,
)
from cygnusx.domain.cookie.repositories import (
    IConsumptionLogRepository,
    ICookieAccountRepository,
    ICookiePricingRepository,
    ICookieTransactionRepository,
    ILedgerRepository,
)
from cygnusx.domain.cookie.value_objects import (
    AccountStatus,
    BillingItem,
    PricingType,
    PricingUnit,
    TransactionType,
)
from cygnusx.infrastructure.database.models.cookie import (
    ConsumptionLogModel,
    CookieAccountModel,
    CookiePricingModel,
    CookieTransactionModel,
    LedgerEntryModel,
)


# ------------------------------------------------------------------
# 账户仓储
# ------------------------------------------------------------------
class SqlAlchemyAccountRepository(ICookieAccountRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_user(self, user_id: UUID) -> CookieAccount | None:
        result = await self._session.execute(
            select(CookieAccountModel).where(CookieAccountModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_id(self, account_id: int) -> CookieAccount | None:
        model = await self._session.get(CookieAccountModel, account_id)
        return self._to_entity(model) if model else None

    async def save(self, account: CookieAccount) -> CookieAccount:
        if account.id is not None:
            model = await self._session.get(CookieAccountModel, account.id)
            if model:
                self._update_model(model, account)
            else:
                model = self._to_model(account)
                self._session.add(model)
        else:
            model = self._to_model(account)
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_all(
        self, status: str | None = None, offset: int = 0, limit: int = 50
    ) -> list[CookieAccount]:
        query = select(CookieAccountModel)
        if status:
            query = query.where(CookieAccountModel.status == status)
        query = query.order_by(desc(CookieAccountModel.created_at)).offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    @staticmethod
    def _to_entity(m: CookieAccountModel) -> CookieAccount:
        return CookieAccount(
            id=m.id,
            user_id=m.user_id,
            balance=m.balance or Decimal("0"),
            frozen_balance=m.frozen_balance or Decimal("0"),
            total_earned=m.total_earned or Decimal("0"),
            total_spent=m.total_spent or Decimal("0"),
            total_adjusted=m.total_adjusted or Decimal("0"),
            status=AccountStatus(m.status),
            frozen_reason=m.frozen_reason or "",
            frozen_by=m.frozen_by,
            frozen_at=m.frozen_at,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(a: CookieAccount) -> CookieAccountModel:
        return CookieAccountModel(
            id=a.id,
            user_id=a.user_id,
            balance=a.balance,
            frozen_balance=a.frozen_balance,
            total_earned=a.total_earned,
            total_spent=a.total_spent,
            total_adjusted=a.total_adjusted,
            status=a.status.value,
            frozen_reason=a.frozen_reason or None,
            frozen_by=a.frozen_by,
            frozen_at=a.frozen_at,
        )

    @staticmethod
    def _update_model(m: CookieAccountModel, a: CookieAccount) -> CookieAccountModel:
        m.balance = a.balance
        m.frozen_balance = a.frozen_balance
        m.total_earned = a.total_earned
        m.total_spent = a.total_spent
        m.total_adjusted = a.total_adjusted
        m.status = a.status.value
        m.frozen_reason = a.frozen_reason or None
        m.frozen_by = a.frozen_by
        m.frozen_at = a.frozen_at
        return m


# ------------------------------------------------------------------
# 交易流水仓储
# ------------------------------------------------------------------
class SqlAlchemyTransactionRepository(ICookieTransactionRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, txn: CookieTransaction) -> CookieTransaction:
        model = CookieTransactionModel(
            account_id=txn.account_id,
            user_id=txn.user_id,
            txn_type=txn.txn_type.value,
            amount=txn.amount,
            balance_after=txn.balance_after,
            source_type=txn.source_type or None,
            source_id=txn.source_id or None,
            admin_id=txn.admin_id,
            adjust_reason=txn.adjust_reason or None,
            task_type=txn.task_type or None,
            resource_cores=txn.resource_cores,
            resource_memory_gb=txn.resource_memory_gb,
            execution_seconds=txn.execution_seconds,
            description=txn.description,
            ip_address=txn.ip_address or None,
            user_agent=txn.user_agent or None,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_by_user(
        self,
        user_id: UUID,
        txn_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[CookieTransaction]:
        query = select(CookieTransactionModel).where(CookieTransactionModel.user_id == user_id)
        if txn_type:
            query = query.where(CookieTransactionModel.txn_type == txn_type)
        query = query.order_by(desc(CookieTransactionModel.created_at)).offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_source(self, source_type: str, source_id: str) -> list[CookieTransaction]:
        result = await self._session.execute(
            select(CookieTransactionModel)
            .where(
                CookieTransactionModel.source_type == source_type,
                CookieTransactionModel.source_id == source_id,
            )
            .order_by(desc(CookieTransactionModel.created_at))
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_by_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).where(CookieTransactionModel.user_id == user_id)
        )
        return result.scalar() or 0

    @staticmethod
    def _to_entity(m: CookieTransactionModel) -> CookieTransaction:
        return CookieTransaction(
            id=m.id,
            account_id=m.account_id,
            user_id=m.user_id,
            txn_type=TransactionType(m.txn_type),
            amount=m.amount or Decimal("0"),
            balance_after=m.balance_after or Decimal("0"),
            source_type=m.source_type or "",
            source_id=m.source_id or "",
            admin_id=m.admin_id,
            adjust_reason=m.adjust_reason or "",
            task_type=m.task_type or "",
            resource_cores=m.resource_cores,
            resource_memory_gb=m.resource_memory_gb,
            execution_seconds=m.execution_seconds,
            description=m.description or "",
            ip_address=m.ip_address or "",
            user_agent=m.user_agent or "",
            created_at=m.created_at,
        )


# ------------------------------------------------------------------
# 定价策略仓储
# ------------------------------------------------------------------
class SqlAlchemyPricingRepository(ICookiePricingRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, pricing_id: int) -> CookiePricing | None:
        model = await self._session.get(CookiePricingModel, pricing_id)
        return self._to_entity(model) if model else None

    async def list_all(self, active_only: bool = True) -> list[CookiePricing]:
        query = select(CookiePricingModel)
        if active_only:
            query = query.where(CookiePricingModel.is_active == True)  # noqa: E712
        query = query.order_by(desc(CookiePricingModel.priority), CookiePricingModel.id)
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def find_match(
        self,
        flow_category: str = "",
        resource_type: str = "",
        pricing_type: str = "",
    ) -> CookiePricing | None:
        """按 flow_category + resource_type + priority 匹配最优定价"""
        query = (
            select(CookiePricingModel)
            .where(
                CookiePricingModel.is_active == True,  # noqa: E712
                CookiePricingModel.effective_from <= func.now(),
            )
            .where(
                (CookiePricingModel.effective_until.is_(None))
                | (CookiePricingModel.effective_until > func.now())
            )
        )
        if flow_category:
            query = query.where(CookiePricingModel.flow_category == flow_category)
        if resource_type:
            query = query.where(CookiePricingModel.resource_type == resource_type)
        if pricing_type:
            query = query.where(CookiePricingModel.pricing_type == pricing_type)
        query = query.order_by(desc(CookiePricingModel.priority)).limit(1)
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, pricing: CookiePricing) -> CookiePricing:
        if pricing.id is not None:
            model = await self._session.get(CookiePricingModel, pricing.id)
            if model:
                self._update_model(model, pricing)
            else:
                model = self._to_model(pricing)
                self._session.add(model)
        else:
            model = self._to_model(pricing)
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, pricing_id: int) -> bool:
        model = await self._session.get(CookiePricingModel, pricing_id)
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    @staticmethod
    def _to_entity(m: CookiePricingModel) -> CookiePricing:
        return CookiePricing(
            id=m.id,
            pricing_type=PricingType(m.pricing_type),
            resource_type=m.resource_type or "",
            flow_category=m.flow_category or "",
            base_cost=m.base_cost or Decimal("0"),
            per_sample_cost=m.per_sample_cost or Decimal("0"),
            per_comparison_cost=m.per_comparison_cost or Decimal("0"),
            unit=PricingUnit(m.unit),
            is_active=m.is_active,
            effective_from=m.effective_from,
            effective_until=m.effective_until,
            priority=m.priority,
            description=m.description or "",
            created_by=m.created_by,
            created_at=m.created_at,
            updated_at=m.updated_at,
            updated_by=m.updated_by,
        )

    @staticmethod
    def _to_model(p: CookiePricing) -> CookiePricingModel:
        return CookiePricingModel(
            id=p.id,
            pricing_type=p.pricing_type.value,
            resource_type=p.resource_type or None,
            flow_category=p.flow_category or None,
            base_cost=p.base_cost,
            per_sample_cost=p.per_sample_cost,
            per_comparison_cost=p.per_comparison_cost,
            unit=p.unit.value,
            is_active=p.is_active,
            effective_from=p.effective_from,
            effective_until=p.effective_until,
            priority=p.priority,
            description=p.description or None,
            created_by=p.created_by,
            updated_by=p.updated_by,
        )

    @staticmethod
    def _update_model(m: CookiePricingModel, p: CookiePricing) -> CookiePricingModel:
        m.pricing_type = p.pricing_type.value
        m.resource_type = p.resource_type or None
        m.flow_category = p.flow_category or None
        m.base_cost = p.base_cost
        m.per_sample_cost = p.per_sample_cost
        m.per_comparison_cost = p.per_comparison_cost
        m.unit = p.unit.value
        m.is_active = p.is_active
        m.effective_from = p.effective_from
        m.effective_until = p.effective_until
        m.priority = p.priority
        m.description = p.description or None
        m.updated_by = p.updated_by
        return m


# ------------------------------------------------------------------
# 消费明细仓储
# ------------------------------------------------------------------
class SqlAlchemyConsumptionLogRepository(IConsumptionLogRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, log: ConsumptionLog) -> ConsumptionLog:
        model = ConsumptionLogModel(
            task_id=log.task_id or None,
            sandbox_session_id=log.sandbox_session_id or None,
            user_id=log.user_id,
            transaction_id=log.transaction_id,
            billing_item=log.billing_item.value,
            quantity=log.quantity,
            unit_price=log.unit_price,
            total_cost=log.total_cost,
            started_at=log.started_at,
            ended_at=log.ended_at,
            duration_seconds=log.duration_seconds,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_by_task(self, task_id: str) -> list[ConsumptionLog]:
        result = await self._session.execute(
            select(ConsumptionLogModel)
            .where(ConsumptionLogModel.task_id == task_id)
            .order_by(ConsumptionLogModel.created_at)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_user(
        self, user_id: UUID, offset: int = 0, limit: int = 50
    ) -> list[ConsumptionLog]:
        result = await self._session.execute(
            select(ConsumptionLogModel)
            .where(ConsumptionLogModel.user_id == user_id)
            .order_by(desc(ConsumptionLogModel.created_at))
            .offset(offset)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    @staticmethod
    def _to_entity(m: ConsumptionLogModel) -> ConsumptionLog:
        return ConsumptionLog(
            id=m.id,
            task_id=m.task_id or "",
            sandbox_session_id=m.sandbox_session_id or "",
            user_id=m.user_id,
            transaction_id=m.transaction_id,
            billing_item=BillingItem(m.billing_item),
            quantity=m.quantity or Decimal("0"),
            unit_price=m.unit_price or Decimal("0"),
            total_cost=m.total_cost or Decimal("0"),
            started_at=m.started_at,
            ended_at=m.ended_at,
            duration_seconds=m.duration_seconds,
            created_at=m.created_at,
        )


# ------------------------------------------------------------------
# 账本仓储
# ------------------------------------------------------------------
class SqlAlchemyLedgerRepository(ILedgerRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, entry: LedgerEntry) -> LedgerEntry:
        model = LedgerEntryModel(
            snapshot_date=entry.snapshot_date,
            user_id=entry.user_id,
            account_id=entry.account_id,
            opening_balance=entry.opening_balance,
            total_earned=entry.total_earned,
            total_spent=entry.total_spent,
            total_adjusted=entry.total_adjusted,
            closing_balance=entry.closing_balance,
            transaction_count=entry.transaction_count,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_by_date_user(self, snapshot_date: date, user_id: UUID) -> LedgerEntry | None:
        result = await self._session.execute(
            select(LedgerEntryModel).where(
                LedgerEntryModel.snapshot_date == snapshot_date,
                LedgerEntryModel.user_id == user_id,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_date(
        self, snapshot_date: date, offset: int = 0, limit: int = 100
    ) -> list[LedgerEntry]:
        result = await self._session.execute(
            select(LedgerEntryModel)
            .where(LedgerEntryModel.snapshot_date == snapshot_date)
            .order_by(LedgerEntryModel.user_id)
            .offset(offset)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    @staticmethod
    def _to_entity(m: LedgerEntryModel) -> LedgerEntry:
        return LedgerEntry(
            id=m.id,
            snapshot_date=m.snapshot_date,
            user_id=m.user_id,
            account_id=m.account_id,
            opening_balance=m.opening_balance or Decimal("0"),
            total_earned=m.total_earned or Decimal("0"),
            total_spent=m.total_spent or Decimal("0"),
            total_adjusted=m.total_adjusted or Decimal("0"),
            closing_balance=m.closing_balance or Decimal("0"),
            transaction_count=m.transaction_count or 0,
            created_at=m.created_at,
        )
