"""饼干积分系统 DTO"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import model_validator

from cygnusx.application.schemas.base import CygnusXBaseSchema


class CookieAccountDTO(CygnusXBaseSchema):
    """账户信息"""

    id: int | None = None
    user_id: UUID
    balance: Decimal = Decimal("0")
    frozen_balance: Decimal = Decimal("0")
    available_balance: Decimal = Decimal("0")
    total_earned: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    total_adjusted: Decimal = Decimal("0")
    status: str = "active"
    created_at: datetime | None = None


class AdminCookieAccountDTO(CookieAccountDTO):
    """管理端账户信息 — 关联用户身份与存储资产，供「饼干账户管理」与「用户管理」共用同一份 JOIN 视图"""

    username: str = ""
    nickname: str | None = None
    email: str = ""
    role: str = ""
    lab_group: str | None = None
    user_status: str = ""
    # 用户侧资产（来自 users 表，便于抽屉展示，无需再请求 /admin/users）
    user_created_at: datetime | None = None
    storage_quota: int = 0
    used_storage: int = 0


class CookieTransactionDTO(CygnusXBaseSchema):
    """交易流水"""

    id: int | None = None
    user_id: UUID
    txn_type: str
    amount: Decimal
    balance_after: Decimal
    source_type: str = ""
    source_id: str = ""
    task_type: str = ""
    description: str = ""
    created_at: datetime | None = None


class CookiePricingDTO(CygnusXBaseSchema):
    """定价策略"""

    id: int | None = None
    pricing_type: str
    resource_type: str = ""
    flow_category: str = ""
    base_cost: Decimal
    per_sample_cost: Decimal = Decimal("0")
    per_comparison_cost: Decimal = Decimal("0")
    unit: str
    is_active: bool = True
    priority: int = 0
    description: str = ""
    effective_from: datetime | None = None
    effective_until: datetime | None = None


class CostEstimateDTO(CygnusXBaseSchema):
    """费用预估"""

    flow_id: str
    estimated_cost: Decimal
    sample_count: int = 0
    comparison_count: int = 0
    breakdown: list[dict] = []
    affordable: bool = True
    current_balance: Decimal = Decimal("0")


class CookieStatsDTO(CygnusXBaseSchema):
    """系统统计"""

    total_accounts: int = 0
    active_accounts: int = 0
    total_balance: Decimal = Decimal("0")
    total_frozen: Decimal = Decimal("0")
    total_earned: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")


class PricingCreateRequest(CygnusXBaseSchema):
    """创建/更新定价策略请求"""

    pricing_type: str
    resource_type: str = ""
    flow_category: str = ""
    base_cost: Decimal
    per_sample_cost: Decimal = Decimal("0")
    per_comparison_cost: Decimal = Decimal("0")
    unit: str
    priority: int = 0
    description: str = ""
    effective_until: datetime | None = None


class CookieDiscountRequest(CygnusXBaseSchema):
    name: str
    discount_multiplier: Decimal
    date_start: date
    date_end: date
    daily_start: time | None = None
    daily_end: time | None = None
    timezone: str = "Asia/Shanghai"
    priority: int = 0
    is_active: bool = True
    banner_title: str
    banner_description: str

    @model_validator(mode="after")
    def validate_window(self):
        if self.date_end < self.date_start:
            raise ValueError("结束日期不能早于开始日期")
        if (self.daily_start is None) != (self.daily_end is None):
            raise ValueError("每日开始时间和结束时间必须同时设置或同时留空")
        if not Decimal("0") <= self.discount_multiplier <= Decimal("1"):
            raise ValueError("折扣倍率必须在 0 到 1 之间")
        return self


class CookieDiscountDTO(CookieDiscountRequest):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AiTokenRateDTO(CygnusXBaseSchema):
    base_rate: Decimal
    effective_rate: Decimal
    discount: CookieDiscountDTO | None = None


class AdjustBalanceRequest(CygnusXBaseSchema):
    """管理员调整余额请求"""

    amount: Decimal
    reason: str = ""


class AccountFreezeRequest(CygnusXBaseSchema):
    """冻结/解冻请求"""

    reason: str = ""
