"""饼干域实体 — 聚合根 + 实体"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.cookie.value_objects import (
    AccountStatus,
    BillingItem,
    PricingType,
    PricingUnit,
    TransactionType,
)


class CookieTransaction(BaseModel):
    """交易流水实体（不可变，插入后不修改）"""

    id: int | None = None
    account_id: int | None = None
    user_id: UUID
    txn_type: TransactionType
    amount: Decimal = Decimal("0")
    balance_after: Decimal = Decimal("0")
    source_type: str = ""
    source_id: str = ""
    admin_id: UUID | None = None
    adjust_reason: str = ""
    task_type: str = ""
    resource_cores: int | None = None
    resource_memory_gb: Decimal | None = None
    execution_seconds: int | None = None
    description: str = ""
    ip_address: str = ""
    user_agent: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class CookiePricing(BaseModel):
    """定价策略实体"""

    id: int | None = None
    pricing_type: PricingType
    resource_type: str = ""
    flow_category: str = ""
    base_cost: Decimal = Decimal("0")
    per_sample_cost: Decimal = Decimal("0")
    per_comparison_cost: Decimal = Decimal("0")
    unit: PricingUnit
    is_active: bool = True
    effective_from: datetime = Field(default_factory=datetime.now)
    effective_until: datetime | None = None
    priority: int = 0
    description: str = ""
    created_by: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    updated_by: UUID | None = None


class ConsumptionLog(BaseModel):
    """消费明细（审计对账）"""

    id: int | None = None
    task_id: str = ""
    sandbox_session_id: str = ""
    user_id: UUID
    transaction_id: int | None = None
    billing_item: BillingItem
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class LedgerEntry(BaseModel):
    """日终账本快照"""

    id: int | None = None
    snapshot_date: datetime
    user_id: UUID
    account_id: int
    opening_balance: Decimal = Decimal("0")
    total_earned: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    total_adjusted: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")
    transaction_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


class CookieAccount(BaseModel):
    """饼干账户聚合根 — 每个用户一个账户"""

    id: int | None = None
    user_id: UUID
    balance: Decimal = Decimal("0")
    frozen_balance: Decimal = Decimal("0")
    total_earned: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    total_adjusted: Decimal = Decimal("0")
    status: AccountStatus = AccountStatus.ACTIVE
    frozen_reason: str = ""
    frozen_by: UUID | None = None
    frozen_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def available_balance(self) -> Decimal:
        """可用余额 = 余额 - 冻结"""
        return self.balance - self.frozen_balance

    @property
    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE

    def can_spend(self, amount: Decimal) -> bool:
        """检查是否有足够余额"""
        return self.is_active and self.available_balance >= amount

    def apply_transaction(self, txn: CookieTransaction) -> None:
        """应用交易到账户（Python 端维护统计，替代 SQL 触发器）"""
        if txn.txn_type == TransactionType.EARN:
            self.balance += txn.amount
            self.total_earned += txn.amount
        elif txn.txn_type in (TransactionType.SPEND, TransactionType.FREEZE):
            self.balance += txn.amount
            self.total_spent += abs(txn.amount)
            if txn.txn_type == TransactionType.FREEZE:
                self.frozen_balance += abs(txn.amount)
        elif txn.txn_type == TransactionType.ADJUST:
            self.balance += txn.amount
            self.total_adjusted += txn.amount
        elif txn.txn_type == TransactionType.REFUND:
            self.balance += txn.amount
        elif txn.txn_type == TransactionType.UNFREEZE:
            self.balance += txn.amount
            self.frozen_balance -= abs(txn.amount)
