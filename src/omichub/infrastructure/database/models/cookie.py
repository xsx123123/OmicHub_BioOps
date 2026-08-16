"""饼干积分系统 ORM 模型 — 5 张表"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class CookieAccountModel(Base, TimestampMixin):
    """饼干账户表 — 每个用户一个账户"""

    __tablename__ = "cookie_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'frozen', 'suspended')", name="chk_account_status"),
        Index("idx_accounts_status", "status", postgresql_where=text("status != 'active'")),
        Index("idx_accounts_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    frozen_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_earned: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_adjusted: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    frozen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CookieTransactionModel(Base):
    """交易流水表 — 核心不可删改"""

    __tablename__ = "cookie_transactions"
    __table_args__ = (
        CheckConstraint(
            "(txn_type != 'earn' OR amount >= 0) AND "
            "(txn_type != 'refund' OR amount >= 0) AND "
            "(txn_type != 'unfreeze' OR amount >= 0) AND "
            "(txn_type NOT IN ('spend', 'freeze') OR amount <= 0)",
            name="chk_txn_amount_sign",
        ),
        Index(
            "idx_txn_user_created",
            "user_id",
            "created_at",
            "txn_type",
            postgresql_using="btree",
        ),
        Index(
            "idx_txn_source",
            "source_type",
            "source_id",
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index("idx_txn_type_created", "txn_type", "created_at"),
        Index("idx_txn_account", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cookie_accounts.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    txn_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    adjust_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_memory_gb: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    execution_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CookiePricingModel(Base, TimestampMixin):
    """定价策略表"""

    __tablename__ = "cookie_pricing"
    __table_args__ = (
        CheckConstraint(
            "pricing_type IN ('task_type', 'resource', 'sandbox', 'bonus')",
            name="chk_pricing_type",
        ),
        CheckConstraint(
            "unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', 'per_session', 'per_user', 'per_sample', 'per_comparison')",
            name="chk_pricing_unit",
        ),
        Index(
            "idx_pricing_query",
            "flow_category",
            "resource_type",
            "priority",
            postgresql_where=text("is_active = TRUE"),
        ),
        Index("idx_pricing_effective", "effective_from", "effective_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pricing_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    flow_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    base_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    per_sample_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    per_comparison_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class CookieDiscountModel(Base, TimestampMixin):
    """AI Token 饼干换算优惠规则。"""

    __tablename__ = "cookie_discounts"
    __table_args__ = (
        CheckConstraint(
            "discount_multiplier >= 0 AND discount_multiplier <= 1",
            name="chk_cookie_discount_multiplier",
        ),
        Index("idx_cookie_discount_active", "is_active", "date_start", "date_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    discount_multiplier: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    date_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_end: Mapped[date] = mapped_column(Date, nullable=False)
    daily_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    daily_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    banner_title: Mapped[str] = mapped_column(String(200), nullable=False)
    banner_description: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class ConsumptionLogModel(Base):
    """消费明细表（审计对账）"""

    __tablename__ = "cookie_consumption_logs"
    __table_args__ = (
        CheckConstraint(
            "billing_item IN ('task_base', 'cpu_usage', 'memory_usage', 'execution_time', "
            "'sandbox_session', 'sandbox_cpu', 'sandbox_memory')",
            name="chk_billing_item",
        ),
        Index("idx_logs_task", "task_id", postgresql_where=text("task_id IS NOT NULL")),
        Index(
            "idx_logs_sandbox",
            "sandbox_session_id",
            postgresql_where=text("sandbox_session_id IS NOT NULL"),
        ),
        Index("idx_logs_user_created", "user_id", "created_at"),
        Index("idx_logs_transaction", "transaction_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sandbox_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cookie_transactions.id"), nullable=True
    )
    billing_item: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntryModel(Base):
    """日终账本快照"""

    __tablename__ = "cookie_ledger"
    __table_args__ = (
        Index("idx_ledger_date", "snapshot_date"),
        Index("idx_ledger_user_date", "user_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cookie_accounts.id"), nullable=False
    )
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_earned: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_adjusted: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
