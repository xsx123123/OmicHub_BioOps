# CygnusX Cookie (饼干) 积分系统 — 完整后端架构设计

> 版本: v1.0 | 适配: Vue3 + FastAPI + PostgreSQL + Redis + Celery + Docker Compose
> 设计目标: 原子性、并发安全、防超支、管理员灵活操作

---

## 目录

1. [数据库设计](#1-数据库设计)
2. [Pydantic DTO 模型定义](#2-pydantic-dto-模型定义)
3. [核心业务逻辑 — CookieService](#3-核心业务逻辑--cookieservice)
4. [定价计算引擎 — PricingEngine](#4-定价计算引擎--pricingengine)
5. [消费拦截器与系统集成](#5-消费拦截器与系统集成)
6. [FastAPI 路由层](#6-fastapi-路由层)
7. [默认定价策略数据](#7-默认定价策略数据)
8. [部署与迁移说明](#8-部署与迁移说明)

---

## 1. 数据库设计

### 1.1 建表SQL

```sql
-- ============================================================
-- 1.1.1 cookie_accounts — 饼干账户表（与用户一对一）
-- ============================================================
CREATE TABLE cookie_accounts (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 余额（DECIMAL 避免浮点精度问题）
    balance         DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    frozen_balance  DECIMAL(12, 2) NOT NULL DEFAULT 0.00,  -- 冻结金额（预扣）

    -- 统计字段（冗余加速查询，通过触发器维护）
    total_earned    DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    total_spent     DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    total_adjusted  DECIMAL(12, 2) NOT NULL DEFAULT 0.00,  -- 累计被管理员调整金额

    -- 账户状态
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
                    -- active / frozen / suspended
                    CHECK (status IN ('active', 'frozen', 'suspended')),

    frozen_reason   TEXT,          -- 冻结/停用原因
    frozen_by       INTEGER REFERENCES users(id),  -- 操作人
    frozen_at       TIMESTAMPTZ,   -- 冻结时间

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id)
);

COMMENT ON TABLE cookie_accounts IS '饼干账户表 — 每个用户一个账户';
COMMENT ON COLUMN cookie_accounts.balance IS '可用余额（不包含冻结部分）';
COMMENT ON COLUMN cookie_accounts.frozen_balance IS '冻结余额（已预扣但未结算）';
COMMENT ON COLUMN cookie_accounts.status IS '账户状态: active正常 frozen冻结 suspended停用';


-- ============================================================
-- 1.1.2 cookie_transactions — 交易流水表（核心，不可删除不可修改）
-- ============================================================
CREATE TABLE cookie_transactions (
    id              BIGSERIAL PRIMARY KEY,  -- 大量流水，用BIGSERIAL

    -- 账户关联
    account_id      INTEGER NOT NULL REFERENCES cookie_accounts(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),  -- 冗余，方便分片查询

    -- 交易类型
    txn_type        VARCHAR(30) NOT NULL,
                    CHECK (txn_type IN (
                        'earn',         -- 获得（签到、奖励、充值）
                        'spend',        -- 消费（任务、沙盒）
                        'adjust',       -- 管理员调整
                        'refund',       -- 退款
                        'freeze',       -- 预扣冻结
                        'unfreeze'      -- 解冻退还
                    )),

    -- 金额（earn为正，spend为负，adjust可正可负）
    amount          DECIMAL(12, 2) NOT NULL,
    balance_after   DECIMAL(12, 2) NOT NULL,  -- 交易后余额

    -- 业务关联
    source_type     VARCHAR(30),  -- task / sandbox / admin / signup / daily / system
    source_id       VARCHAR(100), -- 关联业务ID（task_id / sandbox_session_id）

    -- 管理员操作记录（txn_type = adjust 时必填）
    admin_id        INTEGER REFERENCES users(id),
    adjust_reason   TEXT,

    -- 任务消费详情（source_type = task 时填写）
    task_type       VARCHAR(50),     -- rna_seq / atac_seq / scrna_seq / ...
    resource_cores  INTEGER,         -- 使用核数
    resource_memory_gb DECIMAL(6, 1), -- 使用内存GB
    execution_seconds INTEGER,       -- 执行时长（秒）

    -- 元信息
    description     TEXT NOT NULL,
    ip_address      INET,
    user_agent      TEXT,

    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- 确保earn金额为正，spend金额为负
    CONSTRAINT chk_earn_positive CHECK (
        (txn_type != 'earn' AND txn_type != 'adjust') OR amount >= 0
    ),
    CONSTRAINT chk_spend_negative CHECK (
        (txn_type != 'spend' AND txn_type != 'freeze') OR amount <= 0
    )
);

COMMENT ON TABLE cookie_transactions IS '饼干交易流水 — 核心表，记录所有资金变动，不可删除不可修改';
COMMENT ON COLUMN cookie_transactions.txn_type IS 'earn获得/spend消费/adjust调整/refund退款/freeze预扣/unfreeze解冻';
COMMENT ON COLUMN cookie_transactions.amount IS '变动金额: earn为正 spend为负 adjust可正可负';
COMMENT ON COLUMN cookie_transactions.balance_after IS '交易后的账户余额（实时快照）';


-- ============================================================
-- 1.1.3 cookie_pricing — 定价策略表（管理员可配置）
-- ============================================================
CREATE TABLE cookie_pricing (
    id              SERIAL PRIMARY KEY,

    -- 定价维度（三层维度组合唯一）
    pricing_type    VARCHAR(30) NOT NULL,
                    CHECK (pricing_type IN ('task_type', 'resource', 'sandbox', 'bonus')),
    resource_type   VARCHAR(50),  -- cpu_core_per_hour / memory_gb_per_hour / base_fee
    flow_category   VARCHAR(50),  -- rna_seq / atac_seq / scrna_seq / sandbox / signup

    -- 定价数值
    base_cost       DECIMAL(10, 4) NOT NULL,  -- 每单位消耗饼干数
    unit            VARCHAR(20) NOT NULL,
                    CHECK (unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', 'per_session', 'per_user')),

    -- 配置
    is_active       BOOLEAN DEFAULT TRUE,
    effective_from  TIMESTAMPTZ DEFAULT NOW(),
    effective_until TIMESTAMPTZ,  -- NULL = 长期有效
    priority        INTEGER DEFAULT 0,  -- 优先级（高优先覆盖低优先）
    description     TEXT,

    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_by      INTEGER REFERENCES users(id),

    -- 同一时间范围内同一定价维度只能有一个active策略
    CONSTRAINT uq_pricing_active UNIQUE (pricing_type, resource_type, flow_category, effective_from)
        WHERE is_active = TRUE AND effective_until IS NULL
);

COMMENT ON TABLE cookie_pricing IS '饼干定价策略表 — 支持多维度、时段、优先级配置';


-- ============================================================
-- 1.1.4 cookie_consumption_logs — 消费明细表（任务级，用于审计和对账）
-- ============================================================
CREATE TABLE cookie_consumption_logs (
    id              BIGSERIAL PRIMARY KEY,

    -- 关联业务
    task_id             VARCHAR(100),
    sandbox_session_id  VARCHAR(100),
    user_id             INTEGER NOT NULL REFERENCES users(id),
    transaction_id      BIGINT REFERENCES cookie_transactions(id),

    -- 计费维度
    billing_item    VARCHAR(50) NOT NULL,
                    CHECK (billing_item IN (
                        'task_base', 'cpu_usage', 'memory_usage',
                        'execution_time', 'sandbox_session', 'sandbox_cpu', 'sandbox_memory'
                    )),
    quantity        DECIMAL(10, 4) NOT NULL,    -- 用量（如核时数、GB时数、秒数）
    unit_price      DECIMAL(10, 4) NOT NULL,    -- 单价（饼干/单位）
    total_cost      DECIMAL(10, 2) NOT NULL,    -- 该项总费用 = quantity * unit_price

    -- 执行时间
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    duration_seconds INTEGER,

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE cookie_consumption_logs IS '消费明细表 — 记录每个计费项的详细拆分，用于审计和对账';


-- ============================================================
-- 1.1.5 cookie_ledger — 日终账本快照（支持快速统计和历史回溯）
-- ============================================================
CREATE TABLE cookie_ledger (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_date   DATE NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    account_id      INTEGER NOT NULL REFERENCES cookie_accounts(id),

    opening_balance DECIMAL(12, 2) NOT NULL,  -- 日初余额
    total_earned    DECIMAL(12, 2) NOT NULL DEFAULT 0,
    total_spent     DECIMAL(12, 2) NOT NULL DEFAULT 0,
    total_adjusted  DECIMAL(12, 2) NOT NULL DEFAULT 0,
    closing_balance DECIMAL(12, 2) NOT NULL,  -- 日终余额

    transaction_count INTEGER NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, user_id)
);

COMMENT ON TABLE cookie_ledger IS '日终账本快照 — 用于快速统计和历史余额回溯';
```

---

### 1.2 索引设计

```sql
-- ============================================================
-- 1.2.1 cookie_accounts 索引
-- ============================================================
-- 主键已自动创建: cookie_accounts_pkey
-- 唯一约束已自动创建: cookie_accounts_user_id_key

-- 按状态筛选（管理员查看冻结账户）
CREATE INDEX idx_accounts_status ON cookie_accounts(status)
    WHERE status != 'active';  -- 部分索引，只索引非活跃账户

-- 更新时间（清理/归档用）
CREATE INDEX idx_accounts_updated_at ON cookie_accounts(updated_at);


-- ============================================================
-- 1.2.2 cookie_transactions 索引（查询热点，重点优化）
-- ============================================================
-- 用户查询自己的流水（最常使用，覆盖索引）
CREATE INDEX idx_txn_user_created ON cookie_transactions(user_id, created_at DESC, txn_type)
    INCLUDE (amount, balance_after, source_type, description);

-- 按业务ID查询（退款/对账用）
CREATE INDEX idx_txn_source ON cookie_transactions(source_type, source_id)
    WHERE source_id IS NOT NULL;

-- 管理员按类型筛选
CREATE INDEX idx_txn_type_created ON cookie_transactions(txn_type, created_at DESC);

-- 按账户ID查询（级联统计用）
CREATE INDEX idx_txn_account ON cookie_transactions(account_id, created_at DESC);

-- 管理员操作审计
CREATE INDEX idx_txn_admin ON cookie_transactions(admin_id, created_at DESC)
    WHERE admin_id IS NOT NULL;

-- IP审计（安全追溯）
CREATE INDEX idx_txn_ip ON cookie_transactions(ip_address)
    WHERE ip_address IS NOT NULL;


-- ============================================================
-- 1.2.3 cookie_pricing 索引
-- ============================================================
-- 按流程分类+资源类型查询当前生效的定价
CREATE INDEX idx_pricing_query ON cookie_pricing(flow_category, resource_type, priority DESC)
    WHERE is_active = TRUE AND (effective_until IS NULL OR effective_until > NOW());

-- 按生效时间查询（历史定价回顾）
CREATE INDEX idx_pricing_effective ON cookie_pricing(effective_from, effective_until);


-- ============================================================
-- 1.2.4 cookie_consumption_logs 索引
-- ============================================================
-- 按任务查询消费明细
CREATE INDEX idx_logs_task ON cookie_consumption_logs(task_id)
    WHERE task_id IS NOT NULL;

-- 按沙盒会话查询
CREATE INDEX idx_logs_sandbox ON cookie_consumption_logs(sandbox_session_id)
    WHERE sandbox_session_id IS NOT NULL;

-- 按用户+时间查询消费趋势
CREATE INDEX idx_logs_user_created ON cookie_consumption_logs(user_id, created_at DESC);

-- 按交易ID查询（对账用）
CREATE INDEX idx_logs_transaction ON cookie_consumption_logs(transaction_id);


-- ============================================================
-- 1.2.5 cookie_ledger 索引
-- ============================================================
-- 按日期+用户唯一已有约束
-- 按日期范围查询（统计用）
CREATE INDEX idx_ledger_date ON cookie_ledger(snapshot_date DESC);

-- 按用户查询历史余额
CREATE INDEX idx_ledger_user_date ON cookie_ledger(user_id, snapshot_date DESC);
```

---

### 1.3 触发器函数（自动维护统计字段和更新时间）

```sql
-- ============================================================
-- 1.3.1 自动更新 updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION fn_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON cookie_accounts
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();

CREATE TRIGGER trg_pricing_updated_at
    BEFORE UPDATE ON cookie_pricing
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();


-- ============================================================
-- 1.3.2 交易流水插入时自动更新账户统计
-- ============================================================
CREATE OR REPLACE FUNCTION fn_update_account_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.txn_type = 'earn' THEN
        UPDATE cookie_accounts
        SET total_earned = total_earned + NEW.amount,
            balance = balance + NEW.amount
        WHERE id = NEW.account_id;
    ELSIF NEW.txn_type = 'spend' OR NEW.txn_type = 'freeze' THEN
        UPDATE cookie_accounts
        SET total_spent = total_spent + ABS(NEW.amount),
            balance = balance + NEW.amount  -- amount是负数
        WHERE id = NEW.account_id;
    ELSIF NEW.txn_type = 'adjust' THEN
        UPDATE cookie_accounts
        SET total_adjusted = total_adjusted + NEW.amount,
            balance = balance + NEW.amount
        WHERE id = NEW.account_id;
    ELSIF NEW.txn_type = 'refund' OR NEW.txn_type = 'unfreeze' THEN
        UPDATE cookie_accounts
        SET balance = balance + NEW.amount  -- amount是正数
        WHERE id = NEW.account_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_transaction_insert
    AFTER INSERT ON cookie_transactions
    FOR EACH ROW EXECUTE FUNCTION fn_update_account_stats();


-- ============================================================
-- 1.3.3 用户注册时自动创建饼干账户
-- ============================================================
CREATE OR REPLACE FUNCTION fn_create_cookie_account_on_signup()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO cookie_accounts (user_id, balance, status)
    VALUES (NEW.id, 0.00, 'active');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 如果需要在用户注册时自动创建账户，取消下面注释：
-- CREATE TRIGGER trg_user_signup_create_account
--     AFTER INSERT ON users
--     FOR EACH ROW EXECUTE FUNCTION fn_create_cookie_account_on_signup();
```

---

### 1.4 数据库ER关系图

```
                    ┌─────────────────┐
                    │     users       │
                    │─────────────────│
                    │ id (PK)         │
                    │ username        │
                    │ email           │
                    │ role            │
                    │ is_active       │
                    └────────┬────────┘
                             │ 1:1
                             ▼
                    ┌─────────────────┐
                    │ cookie_accounts │◄──────────────┐
                    │─────────────────│               │
                    │ id (PK)         │               │
                    │ user_id (FK,UNQ)│               │
                    │ balance         │               │
                    │ frozen_balance  │               │
                    │ total_earned    │               │
                    │ total_spent     │               │
                    │ status          │               │
                    └────────┬────────┘               │
                             │ 1:N                     │
         ┌───────────────────┼───────────────────┐    │
         ▼                   ▼                   ▼    │
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────────┐
│cookie_txn       │ │cookie_ledger     │ │cookie_consumption   │
│(BIGSERIAL PK)   │ │(BIGSERIAL PK)    │ │_logs (BIGSERIAL PK) │
│─────────────────│ │──────────────────│ │─────────────────────│
│ account_id (FK) │ │ account_id (FK)  │ │ transaction_id (FK) │
│ user_id (FK)    │ │ user_id (FK)     │ │ user_id (FK)        │
│ txn_type        │ │ snapshot_date    │ │ task_id             │
│ amount          │ │ opening_balance  │ │ billing_item        │
│ balance_after   │ │ closing_balance  │ │ quantity            │
│ source_type     │ │ transaction_cnt  │ │ unit_price          │
│ source_id       │ └──────────────────┘ │ total_cost          │
│ admin_id        │                      └─────────────────────┘
│ description     │
└─────────────────┘

┌─────────────────┐
│ cookie_pricing  │  (独立配置表)
│─────────────────│
│ id (PK)         │
│ pricing_type    │
│ resource_type   │
│ flow_category   │
│ base_cost       │
│ unit            │
│ is_active       │
│ priority        │
└─────────────────┘
```


---

## 2. Pydantic DTO 模型定义

> 文件路径建议: `app/schemas/cookie.py`

```python
"""
CygnusX Cookie (饼干) 积分系统 — Pydantic v2 DTO 定义
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Literal, Any

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# ============================================================
# 2.1 枚举类型
# ============================================================

class AccountStatus(str, Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"


class TransactionType(str, Enum):
    EARN = "earn"
    SPEND = "spend"
    ADJUST = "adjust"
    REFUND = "refund"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"


class SourceType(str, Enum):
    TASK = "task"
    SANDBOX = "sandbox"
    ADMIN = "admin"
    SIGNUP = "signup"
    DAILY = "daily"
    SYSTEM = "system"


class PricingType(str, Enum):
    TASK_TYPE = "task_type"
    RESOURCE = "resource"
    SANDBOX = "sandbox"
    BONUS = "bonus"


class ResourceType(str, Enum):
    CPU_CORE_PER_HOUR = "cpu_core_per_hour"
    MEMORY_GB_PER_HOUR = "memory_gb_per_hour"
    BASE_FEE = "base_fee"


class FlowCategory(str, Enum):
    RNA_SEQ = "rna_seq"
    ATAC_SEQ = "atac_seq"
    SCRNA_SEQ = "scrna_seq"
    SANDBOX = "sandbox"
    SIGNUP = "signup"


class BillingItem(str, Enum):
    TASK_BASE = "task_base"
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    EXECUTION_TIME = "execution_time"
    SANDBOX_SESSION = "sandbox_session"
    SANDBOX_CPU = "sandbox_cpu"
    SANDBOX_MEMORY = "sandbox_memory"


class PricingUnit(str, Enum):
    PER_TASK = "per_task"
    PER_HOUR = "per_hour"
    PER_CORE_HOUR = "per_core_hour"
    PER_GB_HOUR = "per_gb_hour"
    PER_SESSION = "per_session"
    PER_USER = "per_user"


# ============================================================
# 2.2 基础响应模型
# ============================================================

class PageModel(BaseModel):
    """分页包装器"""
    model_config = ConfigDict(from_attributes=True)

    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, le=200, description="每页数量")
    total: int = Field(..., ge=0, description="总记录数")
    pages: int = Field(..., ge=0, description="总页数")
    items: List[Any] = Field(default_factory=list)


class APIResponse(BaseModel):
    """标准API响应"""
    code: int = Field(default=200)
    message: str = Field(default="success")
    data: Optional[Any] = None


# ============================================================
# 2.3 CookieAccount DTO
# ============================================================

class CookieAccountDTO(BaseModel):
    """饼干账户响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    balance: Decimal = Field(..., decimal_places=2, description="可用余额")
    frozen_balance: Decimal = Field(..., decimal_places=2, description="冻结余额")
    effective_balance: Decimal = Field(..., decimal_places=2, description="有效余额 = balance + frozen_balance")
    total_earned: Decimal = Field(..., decimal_places=2)
    total_spent: Decimal = Field(..., decimal_places=2)
    total_adjusted: Decimal = Field(..., decimal_places=2)
    status: AccountStatus
    frozen_reason: Optional[str] = None
    frozen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def compute_effective(self) -> CookieAccountDTO:
        self.effective_balance = self.balance + self.frozen_balance
        return self


class CookieAccountListDTO(BaseModel):
    """管理员视角账户列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str = Field(..., description="用户名（join users表）")
    email: str = Field(..., description="邮箱（join users表）")
    balance: Decimal
    frozen_balance: Decimal
    status: AccountStatus
    total_earned: Decimal
    total_spent: Decimal
    created_at: datetime


class AccountFreezeRequest(BaseModel):
    """冻结账户请求"""
    reason: str = Field(..., min_length=1, max_length=500, description="冻结原因")


class AccountUnfreezeRequest(BaseModel):
    """解冻账户请求"""
    reason: Optional[str] = Field(default=None, max_length=500)


# ============================================================
# 2.4 CookieTransaction DTO
# ============================================================

class CookieTransactionDTO(BaseModel):
    """交易流水响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    user_id: int
    txn_type: TransactionType
    amount: Decimal = Field(..., description="正数=收入，负数=支出")
    balance_after: Decimal
    source_type: Optional[SourceType] = None
    source_id: Optional[str] = None
    admin_id: Optional[int] = None
    admin_username: Optional[str] = None  -- join users
    adjust_reason: Optional[str] = None
    task_type: Optional[str] = None
    resource_cores: Optional[int] = None
    resource_memory_gb: Optional[Decimal] = None
    execution_seconds: Optional[int] = None
    description: str
    ip_address: Optional[str] = None
    created_at: datetime


class TransactionQueryParams(BaseModel):
    """交易流水查询参数"""
    model_config = ConfigDict(from_attributes=True)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    txn_type: Optional[TransactionType] = None
    source_type: Optional[SourceType] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sort_by: Literal["created_at", "amount"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def validate_date_range(self) -> TransactionQueryParams:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be later than date_to")
        return self


class AdminTransactionQueryParams(TransactionQueryParams):
    """管理员交易流水查询（增加用户筛选）"""
    user_id: Optional[int] = None
    admin_id: Optional[int] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None


# ============================================================
# 2.5 CookiePricing DTO
# ============================================================

class CookiePricingDTO(BaseModel):
    """定价策略响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    pricing_type: PricingType
    resource_type: Optional[ResourceType] = None
    flow_category: Optional[FlowCategory] = None
    base_cost: Decimal = Field(..., decimal_places=4, description="每单位饼干数")
    unit: PricingUnit
    is_active: bool
    effective_from: datetime
    effective_until: Optional[datetime] = None
    priority: int
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PricingCreateRequest(BaseModel):
    """新增定价策略请求"""
    pricing_type: PricingType
    resource_type: Optional[ResourceType] = None
    flow_category: Optional[str] = Field(..., min_length=1, max_length=50)
    base_cost: Decimal = Field(..., gt=0, decimal_places=4)
    unit: PricingUnit
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    priority: int = Field(default=0, ge=0, le=999)
    description: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self) -> PricingCreateRequest:
        if self.effective_from and self.effective_until and self.effective_from >= self.effective_until:
            raise ValueError("effective_from must be earlier than effective_until")
        return self


class PricingUpdateRequest(BaseModel):
    """修改定价策略请求"""
    base_cost: Optional[Decimal] = Field(default=None, gt=0)
    is_active: Optional[bool] = None
    effective_until: Optional[datetime] = None
    priority: Optional[int] = Field(default=None, ge=0, le=999)
    description: Optional[str] = Field(default=None, max_length=500)


# ============================================================
# 2.6 Admin Adjust DTO
# ============================================================

class CookieAdjustRequest(BaseModel):
    """管理员调整饼干余额请求"""
    user_id: int = Field(..., gt=0, description="目标用户ID")
    amount: Decimal = Field(..., description="调整金额（正数=充值，负数=扣减）")
    reason: str = Field(..., min_length=1, max_length=500, description="调整原因")

    @field_validator("amount")
    @classmethod
    def validate_amount_nonzero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("adjust amount cannot be zero")
        return v


class CookieAdjustResponse(BaseModel):
    """管理员调整响应"""
    model_config = ConfigDict(from_attributes=True)

    transaction_id: int
    user_id: int
    username: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    reason: str
    created_at: datetime


# ============================================================
# 2.7 Cost Estimation DTO
# ============================================================

class TaskResourceRequest(BaseModel):
    """任务资源请求"""
    cores: int = Field(..., ge=1, le=128, description="CPU核数")
    memory_gb: float = Field(..., ge=0.5, le=1024, description="内存GB")
    estimated_hours: Optional[float] = Field(default=None, ge=0.01, le=720, description="预估执行小时数")


class CostBreakdownItem(BaseModel):
    """费用拆分项"""
    billing_item: BillingItem
    item_name: str = Field(..., description="人类可读名称")
    quantity: Decimal = Field(..., description="用量")
    quantity_unit: str = Field(..., description="用量单位")
    unit_price: Decimal = Field(..., description="单价（饼干）")
    total_cost: Decimal = Field(..., description="该项费用")


class CostEstimateRequest(BaseModel):
    """费用预估请求"""
    flow_category: str = Field(..., min_length=1, max_length=50, description="流程分类")
    resources: TaskResourceRequest


class CostEstimateResponse(BaseModel):
    """费用预估响应"""
    flow_category: str
    has_sufficient_balance: bool
    current_balance: Decimal
    estimated_cost: Decimal
    breakdown: List[CostBreakdownItem]
    estimated_hours: Optional[float] = None


class CostBreakdown(BaseModel):
    """完整费用拆分（用于内部计算）"""
    items: List[CostBreakdownItem] = Field(default_factory=list)
    total: Decimal = Decimal("0")

    @model_validator(mode="after")
    def compute_total(self) -> CostBreakdown:
        self.total = sum((item.total_cost for item in self.items), Decimal("0"))
        return self


# ============================================================
# 2.8 Consumption Log DTO
# ============================================================

class ConsumptionLogDTO(BaseModel):
    """消费明细响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[str] = None
    sandbox_session_id: Optional[str] = None
    user_id: int
    transaction_id: Optional[int] = None
    billing_item: BillingItem
    quantity: Decimal
    unit_price: Decimal
    total_cost: Decimal
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime


# ============================================================
# 2.9 Statistics DTO
# ============================================================

class CookieStatsOverview(BaseModel):
    """饼干统计概览（管理员仪表盘）"""
    model_config = ConfigDict(from_attributes=True)

    total_accounts: int = Field(..., description="总账户数")
    total_circulation: Decimal = Field(..., description="总流通量（所有余额之和）")
    total_earned_all_time: Decimal = Field(..., description="历史总收入")
    total_spent_all_time: Decimal = Field(..., description="历史总消费")
    total_adjusted_all_time: Decimal = Field(..., description="历史总调整")
    active_accounts: int = Field(..., description="活跃账户数")
    frozen_accounts: int = Field(..., description="冻结账户数")
    suspended_accounts: int = Field(..., description="停用账户数")
    transactions_today: int = Field(..., description="今日交易数")
    transactions_this_month: int = Field(..., description="本月交易数")


class TopUserDTO(BaseModel):
    """Top用户统计"""
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    balance: Decimal
    total_earned: Decimal
    total_spent: Decimal
    transaction_count: int


class CookieStatsResponse(BaseModel):
    """统计响应"""
    model_config = ConfigDict(from_attributes=True)

    overview: CookieStatsOverview
    top_earners: List[TopUserDTO] = Field(default_factory=list)
    top_spenders: List[TopUserDTO] = Field(default_factory=list)
    daily_stats: List[DailyStatDTO] = Field(default_factory=list)


class DailyStatDTO(BaseModel):
    """每日统计"""
    model_config = ConfigDict(from_attributes=True)

    date: date
    total_earned: Decimal
    total_spent: Decimal
    total_adjusted: Decimal
    transaction_count: int
    unique_users: int


# ============================================================
# 2.10 预扣/结算相关 DTO
# ============================================================

class PrefreezeRequest(BaseModel):
    """预扣饼干请求"""
    user_id: int = Field(..., gt=0)
    amount: Decimal = Field(..., gt=0)
    source_type: str = Field(..., min_length=1, max_length=30)
    source_id: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=255)


class PrefreezeResponse(BaseModel):
    """预扣响应"""
    success: bool
    transaction_id: Optional[int] = None
    prefreeze_amount: Decimal
    available_balance: Decimal
    message: str


class SettlementRequest(BaseModel):
    """结算请求（任务完成后调用）"""
    source_id: str = Field(..., description="业务ID（如task_id）")
    actual_cost: Optional[Decimal] = Field(default=None, description="实际费用（None则按实际执行计算）")
    started_at: datetime
    completed_at: datetime
    resources: TaskResourceRequest
    flow_category: str


class SandboxBillingTick(BaseModel):
    """沙盒计费心跳"""
    sandbox_session_id: str
    user_id: int
    elapsed_seconds: int
    cores: int
    memory_gb: float


# ============================================================
# 2.11 错误响应
# ============================================================

class InsufficientBalanceError(BaseModel):
    """余额不足错误"""
    code: Literal[402] = 402
    error: str = "insufficient_balance"
    message: str = "饼干余额不足，请先充值或联系管理员"
    current_balance: Decimal
    required_amount: Decimal


class AccountFrozenError(BaseModel):
    """账户冻结错误"""
    code: Literal[403] = 403
    error: str = "account_frozen"
    message: str = "账户已被冻结，无法执行此操作"
    frozen_reason: Optional[str] = None


---

## 3. 核心业务逻辑 — CookieService

> 文件路径建议: `app/services/cookie_service.py`

```python
"""
CygnusX Cookie (饼干) 积分系统 — 核心业务服务

核心设计原则:
1. 所有余额操作通过 cookie_transactions 表记录（不可篡改审计链）
2. 使用 SELECT FOR UPDATE 实现悲观锁，防止并发超支
3. 余额 = SUM(txn.amount)，cookie_accounts.balance 为缓存加速字段
4. 预扣-结算模式：任务提交时预扣，完成后根据实际用量结算
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, insert, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    CookieAccount, CookieTransaction, CookiePricing,
    CookieConsumptionLog, User, CookieLedger
)
from app.schemas.cookie import (
    CookieAccountDTO, CookieTransactionDTO, CostBreakdown, CostBreakdownItem,
    BillingItem, TransactionQueryParams, AdminTransactionQueryParams,
    PageModel, CookieStatsOverview, TopUserDTO, DailyStatDTO,
    CookieStatsResponse, CookieAdjustResponse, ConsumptionLogDTO
)
from app.exceptions import (
    InsufficientBalanceException, AccountFrozenException,
    AccountNotFoundException, InvalidTransactionException
)

logger = logging.getLogger(__name__)


# ============================================================
# 3.1 CookieService 主类
# ============================================================

class CookieService:
    """饼干核心业务服务 — 所有资金操作的唯一入口"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────────
    # 3.1.1 账户管理
    # ──────────────────────────────────────────

    async def get_or_create_account(self, user_id: int) -> CookieAccount:
        """获取或创建用户饼干账户（用户首次访问时自动创建）"""
        # 先尝试查询
        result = await self.db.execute(
            select(CookieAccount).where(CookieAccount.user_id == user_id)
        )
        account = result.scalar_one_or_none()

        if account is not None:
            return account

        # 不存在则创建（并发安全：利用数据库UNIQUE约束）
        account = CookieAccount(
            user_id=user_id,
            balance=Decimal("0.00"),
            frozen_balance=Decimal("0.00"),
            total_earned=Decimal("0.00"),
            total_spent=Decimal("0.00"),
            total_adjusted=Decimal("0.00"),
            status="active"
        )
        self.db.add(account)
        await self.db.flush()  # 获取ID
        await self.db.refresh(account)
        logger.info(f"[Cookie] Created new account for user_id={user_id}, account_id={account.id}")
        return account

    async def get_account_by_user(self, user_id: int, lock: bool = False) -> Optional[CookieAccount]:
        """根据用户ID获取账户，可选加悲观锁"""
        query = select(CookieAccount).where(CookieAccount.user_id == user_id)
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_account_by_id(self, account_id: int, lock: bool = False) -> Optional[CookieAccount]:
        """根据账户ID获取，可选加悲观锁"""
        query = select(CookieAccount).where(CookieAccount.id == account_id)
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def ensure_account(self, user_id: int, lock: bool = False) -> CookieAccount:
        """确保账户存在，不存在则创建"""
        account = await self.get_account_by_user(user_id, lock=lock)
        if account is None:
            if lock:
                # 已经有锁的情况下不能开新事务，直接创建
                account = CookieAccount(
                    user_id=user_id,
                    balance=Decimal("0.00"),
                    frozen_balance=Decimal("0.00"),
                    status="active"
                )
                self.db.add(account)
                await self.db.flush()
            else:
                account = await self.get_or_create_account(user_id)
        return account

    # ──────────────────────────────────────────
    # 3.1.2 核心消费操作（原子性，防超支）
    # ──────────────────────────────────────────

    async def spend(
        self,
        user_id: int,
        amount: Decimal,
        source_type: str,
        source_id: str,
        description: str,
        task_details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ) -> CookieTransaction:
        """
        消费饼干 — 原子操作，防超支

        流程:
        1. 开启事务，SELECT FOR UPDATE 锁定账户行
        2. 检查账户状态（不能是 frozen/suspended）
        3. 检查余额是否充足
        4. 扣除余额 + 记录流水（同一事务）
        5. 提交事务，释放锁

        Args:
            user_id: 用户ID
            amount: 消费金额（正数，内部转为负数）
            source_type: 业务来源（task/sandbox/admin等）
            source_id: 业务ID
            description: 交易描述
            task_details: 任务详情（task_type, resource_cores, resource_memory_gb, execution_seconds）
            ip_address: 操作IP

        Returns:
            CookieTransaction: 交易记录

        Raises:
            InsufficientBalanceException: 余额不足
            AccountFrozenException: 账户冻结
        """
        amount = abs(amount)  # 确保为正
        amount_neg = -amount  # 存储为负数

        # 步骤1：获取账户并加行锁
        account = await self.ensure_account(user_id, lock=True)

        # 步骤2：检查账户状态
        if account.status == "frozen":
            raise AccountFrozenException(
                f"Account frozen: {account.frozen_reason or 'No reason provided'}"
            )
        if account.status == "suspended":
            raise AccountFrozenException(
                f"Account suspended: {account.frozen_reason or 'No reason provided'}"
            )

        # 步骤3：检查余额
        if account.balance < amount:
            raise InsufficientBalanceException(
                current_balance=account.balance,
                required_amount=amount,
                message=f"饼干余额不足。需要 {amount}，当前余额 {account.balance}"
            )

        # 步骤4：计算交易后余额
        balance_after = account.balance - amount

        # 步骤5：创建交易记录
        txn_data = {
            "account_id": account.id,
            "user_id": user_id,
            "txn_type": "spend",
            "amount": amount_neg,
            "balance_after": balance_after,
            "source_type": source_type,
            "source_id": str(source_id) if source_id else None,
            "description": description,
            "ip_address": ip_address,
        }

        if task_details:
            txn_data.update({
                "task_type": task_details.get("task_type"),
                "resource_cores": task_details.get("resource_cores"),
                "resource_memory_gb": task_details.get("resource_memory_gb"),
                "execution_seconds": task_details.get("execution_seconds"),
            })

        transaction = CookieTransaction(**txn_data)
        self.db.add(transaction)

        # 步骤6：更新账户余额（通过触发器也会更新，但显式更新更可靠）
        account.balance = balance_after
        account.total_spent += amount

        await self.db.flush()
        await self.db.refresh(transaction)

        logger.info(
            f"[Cookie] SPEND user={user_id} amount={amount_neg} "
            f"balance_after={balance_after} source={source_type}:{source_id}"
        )
        return transaction

    # ──────────────────────────────────────────
    # 3.1.3 获得饼干
    # ──────────────────────────────────────────

    async def earn(
        self,
        user_id: int,
        amount: Decimal,
        source_type: str,
        description: str,
        source_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> CookieTransaction:
        """
        获得饼干（注册奖励、签到、管理员充值等）

        Args:
            user_id: 用户ID
            amount: 获得金额（正数）
            source_type: 来源类型
            description: 描述
            source_id: 关联业务ID
            ip_address: 操作IP
        """
        amount = abs(amount)  # 确保为正

        account = await self.ensure_account(user_id, lock=True)

        # 冻结和停用账户也可以获得饼干（比如退款）
        balance_after = account.balance + amount

        transaction = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="earn",
            amount=amount,
            balance_after=balance_after,
            source_type=source_type,
            source_id=str(source_id) if source_id else None,
            description=description,
            ip_address=ip_address,
        )
        self.db.add(transaction)

        account.balance = balance_after
        account.total_earned += amount

        await self.db.flush()
        await self.db.refresh(transaction)

        logger.info(
            f"[Cookie] EARN user={user_id} amount=+{amount} "
            f"balance_after={balance_after} source={source_type}"
        )
        return transaction

    # ──────────────────────────────────────────
    # 3.1.4 管理员调整（可正可负）
    # ──────────────────────────────────────────

    async def adjust(
        self,
        admin_id: int,
        user_id: int,
        amount: Decimal,
        reason: str,
        ip_address: Optional[str] = None
    ) -> CookieAdjustResponse:
        """
        管理员调整余额 — 可正（充值）可负（扣减）

        Args:
            admin_id: 操作管理员ID
            user_id: 目标用户ID
            amount: 调整金额（正=充值，负=扣减）
            reason: 调整原因
            ip_address: 操作IP

        Returns:
            CookieAdjustResponse: 调整结果

        Raises:
            InsufficientBalanceException: 扣减时余额不足
        """
        account = await self.ensure_account(user_id, lock=True)
        balance_before = account.balance
        balance_after = balance_before + amount

        # 检查扣减后余额不能为负
        if balance_after < 0:
            raise InsufficientBalanceException(
                current_balance=balance_before,
                required_amount=abs(amount),
                message=f"扣减后余额将为负数。当前余额 {balance_before}，扣减 {abs(amount)}"
            )

        # 获取管理员用户名
        result = await self.db.execute(
            select(User.username).where(User.id == user_id)
        )
        username = result.scalar() or "unknown"

        transaction = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="adjust",
            amount=amount,  # 可正可负
            balance_after=balance_after,
            source_type="admin",
            admin_id=admin_id,
            adjust_reason=reason,
            description=f"管理员调整: {reason} ({amount:+.2f})",
            ip_address=ip_address,
        )
        self.db.add(transaction)

        account.balance = balance_after
        account.total_adjusted += amount

        await self.db.flush()

        logger.info(
            f"[Cookie] ADJUST admin={admin_id} user={user_id} "
            f"amount={amount:+.2f} balance={balance_before} -> {balance_after}"
        )

        return CookieAdjustResponse(
            transaction_id=transaction.id,
            user_id=user_id,
            username=username,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=reason,
            created_at=datetime.utcnow()
        )

    # ──────────────────────────────────────────
    # 3.1.5 预扣操作（任务提交时）
    # ──────────────────────────────────────────

    async def prefreeze(
        self,
        user_id: int,
        amount: Decimal,
        source_type: str,
        source_id: str,
        description: str
    ) -> CookieTransaction:
        """
        预扣饼干 — 任务提交时冻结预估费用

        流程:
        1. 从 balance 扣除，加到 frozen_balance
        2. 记录一条 freeze 类型的交易流水

        Returns:
            CookieTransaction: 冻结交易记录
        """
        amount = abs(amount)

        account = await self.ensure_account(user_id, lock=True)

        # 检查状态
        if account.status != "active":
            raise AccountFrozenException(f"Account status: {account.status}")

        # 检查可用余额（balance 不包含 frozen_balance）
        if account.balance < amount:
            raise InsufficientBalanceException(
                current_balance=account.balance,
                required_amount=amount
            )

        balance_after = account.balance - amount  # 可用余额减少

        transaction = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="freeze",
            amount=-amount,  # 负数表示支出
            balance_after=balance_after,
            source_type=source_type,
            source_id=str(source_id),
            description=f"[预扣] {description}",
        )
        self.db.add(transaction)

        # 更新账户：可用余额减少，冻结余额增加
        account.balance = balance_after
        account.frozen_balance += amount

        await self.db.flush()
        logger.info(
            f"[Cookie] FREEZE user={user_id} amount={amount} "
            f"source={source_type}:{source_id}"
        )
        return transaction

    # ──────────────────────────────────────────
    # 3.1.6 结算操作（任务完成时）
    # ──────────────────────────────────────────

    async def settle(
        self,
        user_id: int,
        source_id: str,
        actual_cost: Decimal,
        prefreeze_amount: Decimal,
        description: str
    ) -> List[CookieTransaction]:
        """
        结算 — 任务完成后根据实际费用多退少补

        流程:
        1. 解冻预扣金额（unfreeze: frozen_balance -= prefreeze, balance += prefreeze）
        2. 扣除实际费用（spend: balance -= actual_cost）
        3. 如果预扣 > 实际，差额自动退还到 balance

        Returns:
            List[CookieTransaction]: 产生的交易记录（解冻+消费）
        """
        transactions = []
        actual_cost = abs(actual_cost)

        account = await self.ensure_account(user_id, lock=True)

        # 步骤1: 解冻预扣金额
        unfreeze_balance_after = account.balance + prefreeze_amount
        unfreeze_txn = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="unfreeze",
            amount=prefreeze_amount,  # 正数 = 余额增加
            balance_after=unfreeze_balance_after,
            source_type="task",
            source_id=str(source_id),
            description=f"[解冻] 任务完成，解冻预扣 {prefreeze_amount}",
        )
        self.db.add(unfreeze_txn)
        account.balance = unfreeze_balance_after
        account.frozen_balance = max(Decimal("0"), account.frozen_balance - prefreeze_amount)
        transactions.append(unfreeze_txn)

        # 步骤2: 扣除实际费用
        spend_balance_after = account.balance - actual_cost
        spend_txn = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="spend",
            amount=-actual_cost,  # 负数
            balance_after=spend_balance_after,
            source_type="task",
            source_id=str(source_id),
            description=f"[结算] {description}",
        )
        self.db.add(spend_txn)
        account.balance = spend_balance_after
        account.total_spent += actual_cost
        transactions.append(spend_txn)

        await self.db.flush()

        refund = prefreeze_amount - actual_cost
        logger.info(
            f"[Cookie] SETTLE user={user_id} source={source_id} "
            f"prefreeze={prefreeze_amount} actual={actual_cost} "
            f"refund={refund} balance={spend_balance_after}"
        )
        return transactions

    # ──────────────────────────────────────────
    # 3.1.7 取消预扣（任务取消/失败时）
    # ──────────────────────────────────────────

    async def cancel_prefreeze(
        self,
        user_id: int,
        source_id: str,
        prefreeze_amount: Decimal,
        reason: str = "任务取消"
    ) -> CookieTransaction:
        """
        取消预扣 — 任务取消或失败时全额退还

        Returns:
            CookieTransaction: 解冻交易记录
        """
        account = await self.ensure_account(user_id, lock=True)

        balance_after = account.balance + prefreeze_amount
        txn = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="unfreeze",
            amount=prefreeze_amount,
            balance_after=balance_after,
            source_type="task",
            source_id=str(source_id),
            description=f"[退还] {reason}，退还预扣 {prefreeze_amount}",
        )
        self.db.add(txn)

        account.balance = balance_after
        account.frozen_balance = max(Decimal("0"), account.frozen_balance - prefreeze_amount)

        await self.db.flush()
        logger.info(
            f"[Cookie] CANCEL_FREEZE user={user_id} source={source_id} "
            f"refund={prefreeze_amount}"
        )
        return txn

    # ──────────────────────────────────────────
    # 3.1.8 退款
    # ──────────────────────────────────────────

    async def refund(
        self,
        user_id: int,
        amount: Decimal,
        source_type: str,
        source_id: str,
        reason: str,
        admin_id: Optional[int] = None
    ) -> CookieTransaction:
        """
        退款操作（部分或全额退款）

        冻结/停用账户也可以退款
        """
        amount = abs(amount)
        account = await self.ensure_account(user_id, lock=True)

        balance_after = account.balance + amount

        txn = CookieTransaction(
            account_id=account.id,
            user_id=user_id,
            txn_type="refund",
            amount=amount,
            balance_after=balance_after,
            source_type=source_type,
            source_id=str(source_id),
            admin_id=admin_id,
            adjust_reason=reason,
            description=f"[退款] {reason} +{amount}",
        )
        self.db.add(txn)
        account.balance = balance_after

        await self.db.flush()
        logger.info(f"[Cookie] REFUND user={user_id} amount=+{amount} reason={reason}")
        return txn

    # ──────────────────────────────────────────
    # 3.1.9 余额检查
    # ──────────────────────────────────────────

    async def check_balance(self, user_id: int, required: Decimal) -> bool:
        """检查余额是否充足（不包含冻结部分）"""
        account = await self.get_account_by_user(user_id)
        if account is None:
            return required <= 0
        if account.status != "active":
            return False
        return account.balance >= required

    async def get_balance(self, user_id: int) -> Decimal:
        """获取当前可用余额"""
        account = await self.get_account_by_user(user_id)
        return account.balance if account else Decimal("0")

    # ──────────────────────────────────────────
    # 3.1.10 账户冻结/解冻
    # ──────────────────────────────────────────

    async def freeze_account(
        self,
        user_id: int,
        reason: str,
        admin_id: int
    ) -> CookieAccount:
        """冻结账户"""
        account = await self.ensure_account(user_id, lock=True)
        account.status = "frozen"
        account.frozen_reason = reason
        account.frozen_by = admin_id
        account.frozen_at = datetime.utcnow()
        await self.db.flush()
        logger.info(f"[Cookie] FREEZE_ACCOUNT user={user_id} by_admin={admin_id} reason={reason}")
        return account

    async def unfreeze_account(
        self,
        user_id: int,
        reason: Optional[str] = None
    ) -> CookieAccount:
        """解冻账户"""
        account = await self.ensure_account(user_id, lock=True)
        account.status = "active"
        account.frozen_reason = None
        account.frozen_by = None
        account.frozen_at = None
        await self.db.flush()
        logger.info(f"[Cookie] UNFREEZE_ACCOUNT user={user_id} reason={reason}")
        return account

    async def suspend_account(
        self,
        user_id: int,
        reason: str,
        admin_id: int
    ) -> CookieAccount:
        """停用账户（更严厉，需要管理员才能恢复）"""
        account = await self.ensure_account(user_id, lock=True)
        account.status = "suspended"
        account.frozen_reason = reason
        account.frozen_by = admin_id
        account.frozen_at = datetime.utcnow()
        await self.db.flush()
        logger.warning(f"[Cookie] SUSPEND_ACCOUNT user={user_id} by_admin={admin_id} reason={reason}")
        return account


    # ──────────────────────────────────────────
    # 3.1.11 交易历史查询（用户视角）
    # ──────────────────────────────────────────

    async def get_transaction_history(
        self,
        user_id: int,
        params: TransactionQueryParams
    ) -> PageModel:
        """获取用户交易历史（分页、筛选）"""
        # 构建基础查询
        base_query = select(CookieTransaction).where(
            CookieTransaction.user_id == user_id
        )

        # 筛选条件
        if params.txn_type:
            base_query = base_query.where(CookieTransaction.txn_type == params.txn_type.value)
        if params.source_type:
            base_query = base_query.where(CookieTransaction.source_type == params.source_type.value)
        if params.date_from:
            base_query = base_query.where(CookieTransaction.created_at >= params.date_from)
        if params.date_to:
            base_query = base_query.where(CookieTransaction.created_at <= params.date_to)

        # 排序
        sort_col = CookieTransaction.created_at if params.sort_by == "created_at" else CookieTransaction.amount
        if params.sort_order == "desc":
            base_query = base_query.order_by(desc(sort_col))
        else:
            base_query = base_query.order_by(sort_col)

        # 先查总数
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # 分页
        offset = (params.page - 1) * params.page_size
        paginated_query = base_query.offset(offset).limit(params.page_size)

        result = await self.db.execute(paginated_query)
        items = result.scalars().all()

        # 转换为DTO
        dtos = [CookieTransactionDTO.model_validate(t) for t in items]

        return PageModel(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=(total + params.page_size - 1) // params.page_size,
            items=dtos
        )

    # ──────────────────────────────────────────
    # 3.1.12 管理员：所有交易流水查询
    # ──────────────────────────────────────────

    async def admin_get_all_transactions(
        self,
        params: AdminTransactionQueryParams
    ) -> PageModel:
        """管理员获取所有交易流水（高级筛选）"""
        base_query = select(CookieTransaction)

        # 筛选
        if params.user_id:
            base_query = base_query.where(CookieTransaction.user_id == params.user_id)
        if params.txn_type:
            base_query = base_query.where(CookieTransaction.txn_type == params.txn_type.value)
        if params.source_type:
            base_query = base_query.where(CookieTransaction.source_type == params.source_type.value)
        if params.admin_id:
            base_query = base_query.where(CookieTransaction.admin_id == params.admin_id)
        if params.date_from:
            base_query = base_query.where(CookieTransaction.created_at >= params.date_from)
        if params.date_to:
            base_query = base_query.where(CookieTransaction.created_at <= params.date_to)
        if params.min_amount is not None:
            base_query = base_query.where(CookieTransaction.amount >= params.min_amount)
        if params.max_amount is not None:
            base_query = base_query.where(CookieTransaction.amount <= params.max_amount)

        sort_col = CookieTransaction.created_at if params.sort_by == "created_at" else CookieTransaction.amount
        if params.sort_order == "desc":
            base_query = base_query.order_by(desc(sort_col))
        else:
            base_query = base_query.order_by(sort_col)

        # 计数
        count_query = select(func.count()).select_from(base_query.subquery())
        total = (await self.db.execute(count_query)).scalar()

        # 分页
        offset = (params.page - 1) * params.page_size
        result = await self.db.execute(base_query.offset(offset).limit(params.page_size))
        items = [CookieTransactionDTO.model_validate(t) for t in result.scalars().all()]

        return PageModel(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=(total + params.page_size - 1) // params.page_size,
            items=items
        )

    # ──────────────────────────────────────────
    # 3.1.13 管理员：所有账户查询
    # ──────────────────────────────────────────

    async def admin_get_all_accounts(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> PageModel:
        """管理员查看所有用户饼干账户"""
        base_query = select(
            CookieAccount,
            User.username,
            User.email
        ).join(User, CookieAccount.user_id == User.id)

        if search:
            base_query = base_query.where(
                or_(
                    User.username.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%"),
                    CookieAccount.user_id.cast(str) == search
                )
            )
        if status:
            base_query = base_query.where(CookieAccount.status == status)

        # 排序
        sort_mapping = {
            "balance": CookieAccount.balance,
            "created_at": CookieAccount.created_at,
            "total_spent": CookieAccount.total_spent,
        }
        sort_col = sort_mapping.get(sort_by, CookieAccount.created_at)
        if sort_order == "desc":
            base_query = base_query.order_by(desc(sort_col))
        else:
            base_query = base_query.order_by(sort_col)

        # 计数
        count_query = select(func.count()).select_from(base_query.subquery())
        total = (await self.db.execute(count_query)).scalar()

        # 分页
        offset = (page - 1) * page_size
        result = await self.db.execute(base_query.offset(offset).limit(page_size))

        items = []
        for row in result.all():
            account, username, email = row
            dto = CookieAccountListDTO(
                id=account.id,
                user_id=account.user_id,
                username=username,
                email=email,
                balance=account.balance,
                frozen_balance=account.frozen_balance,
                status=account.status,
                total_earned=account.total_earned,
                total_spent=account.total_spent,
                created_at=account.created_at
            )
            items.append(dto)

        return PageModel(
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
            items=items
        )

    # ──────────────────────────────────────────
    # 3.1.14 管理员：统计仪表盘
    # ──────────────────────────────────────────

    async def get_stats(self) -> CookieStatsResponse:
        """获取饼干统计仪表盘数据"""

        # 账户统计
        account_stats = await self.db.execute(
            select(
                func.count().label("total"),
                func.sum(CookieAccount.balance).label("total_circulation"),
                func.sum(CookieAccount.total_earned).label("total_earned"),
                func.sum(CookieAccount.total_spent).label("total_spent"),
                func.sum(CookieAccount.total_adjusted).label("total_adjusted"),
                func.count().filter(CookieAccount.status == "active").label("active"),
                func.count().filter(CookieAccount.status == "frozen").label("frozen"),
                func.count().filter(CookieAccount.status == "suspended").label("suspended"),
            )
        )
        astats = account_stats.one()

        # 今日交易数
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        txn_today = await self.db.execute(
            select(func.count())
            .where(CookieTransaction.created_at >= today_start)
        )
        tx_today = txn_today.scalar()

        # 本月交易数
        month_start = today_start.replace(day=1)
        txn_month = await self.db.execute(
            select(func.count())
            .where(CookieTransaction.created_at >= month_start)
        )
        tx_month = txn_month.scalar()

        overview = CookieStatsOverview(
            total_accounts=astats.total or 0,
            total_circulation=astats.total_circulation or Decimal("0"),
            total_earned_all_time=astats.total_earned or Decimal("0"),
            total_spent_all_time=astats.total_spent or Decimal("0"),
            total_adjusted_all_time=astats.total_adjusted or Decimal("0"),
            active_accounts=astats.active or 0,
            frozen_accounts=astats.frozen or 0,
            suspended_accounts=astats.suspended or 0,
            transactions_today=tx_today or 0,
            transactions_this_month=tx_month or 0,
        )

        # Top 消费用户
        top_spenders_result = await self.db.execute(
            select(
                CookieAccount.user_id,
                User.username,
                CookieAccount.balance,
                CookieAccount.total_earned,
                CookieAccount.total_spent,
            )
            .join(User, CookieAccount.user_id == User.id)
            .order_by(desc(CookieAccount.total_spent))
            .limit(10)
        )
        top_spenders = [
            TopUserDTO(
                user_id=row.user_id,
                username=row.username,
                balance=row.balance,
                total_earned=row.total_earned,
                total_spent=row.total_spent,
                transaction_count=0,  # 可通过子查询优化
            )
            for row in top_spenders_result.all()
        ]

        # Top 高收入用户
        top_earners_result = await self.db.execute(
            select(
                CookieAccount.user_id,
                User.username,
                CookieAccount.balance,
                CookieAccount.total_earned,
                CookieAccount.total_spent,
            )
            .join(User, CookieAccount.user_id == User.id)
            .order_by(desc(CookieAccount.total_earned))
            .limit(10)
        )
        top_earners = [
            TopUserDTO(
                user_id=row.user_id,
                username=row.username,
                balance=row.balance,
                total_earned=row.total_earned,
                total_spent=row.total_spent,
                transaction_count=0,
            )
            for row in top_earners_result.all()
        ]

        # 最近7天每日统计
        daily_result = await self.db.execute(
            select(
                func.date(CookieTransaction.created_at).label("date"),
                func.sum(CookieTransaction.amount).filter(CookieTransaction.txn_type == "earn").label("earned"),
                func.sum(func.abs(CookieTransaction.amount)).filter(CookieTransaction.txn_type == "spend").label("spent"),
                func.sum(CookieTransaction.amount).filter(CookieTransaction.txn_type == "adjust").label("adjusted"),
                func.count().label("txn_count"),
                func.count(func.distinct(CookieTransaction.user_id)).label("unique_users"),
            )
            .where(CookieTransaction.created_at >= today_start - __import__("datetime").timedelta(days=30))
            .group_by(func.date(CookieTransaction.created_at))
            .order_by(desc(func.date(CookieTransaction.created_at)))
            .limit(30)
        )
        daily_stats = [
            DailyStatDTO(
                date=row.date,
                total_earned=row.earned or Decimal("0"),
                total_spent=row.spent or Decimal("0"),
                total_adjusted=row.adjusted or Decimal("0"),
                transaction_count=row.txn_count or 0,
                unique_users=row.unique_users or 0,
            )
            for row in daily_result.all()
        ]

        return CookieStatsResponse(
            overview=overview,
            top_earners=top_earners,
            top_spenders=top_spenders,
            daily_stats=daily_stats,
        )

    # ──────────────────────────────────────────
    # 3.1.15 消费明细记录
    # ──────────────────────────────────────────

    async def log_consumption(
        self,
        user_id: int,
        billing_item: BillingItem,
        quantity: Decimal,
        unit_price: Decimal,
        total_cost: Decimal,
        task_id: Optional[str] = None,
        sandbox_session_id: Optional[str] = None,
        transaction_id: Optional[int] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        duration_seconds: Optional[int] = None,
    ) -> CookieConsumptionLog:
        """记录消费明细（用于审计和对账）"""
        log = CookieConsumptionLog(
            user_id=user_id,
            task_id=task_id,
            sandbox_session_id=sandbox_session_id,
            transaction_id=transaction_id,
            billing_item=billing_item.value,
            quantity=quantity,
            unit_price=unit_price,
            total_cost=total_cost,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    # ──────────────────────────────────────────
    # 3.1.16 日终快照（定时任务调用）
    # ──────────────────────────────────────────

    async def create_daily_ledger(self, snapshot_date: date) -> int:
        """
        创建日终账本快照
        由 Celery 定时任务每日 00:05 调用

        Returns:
            创建的快照记录数
        """
        result = await self.db.execute(
            select(CookieAccount)
        )
        accounts = result.scalars().all()

        count = 0
        for account in accounts:
            # 获取昨日快照作为 opening_balance
            yesterday = snapshot_date - __import__("datetime").timedelta(days=1)
            prev_ledger = await self.db.execute(
                select(CookieLedger)
                .where(
                    CookieLedger.user_id == account.user_id,
                    CookieLedger.snapshot_date == yesterday
                )
            )
            prev = prev_ledger.scalar_one_or_none()
            opening = prev.closing_balance if prev else Decimal("0")

            # 统计当日交易
            day_start = datetime.combine(snapshot_date, __import__("datetime").time.min)
            day_end = datetime.combine(snapshot_date, __import__("datetime").time.max)
            day_stats = await self.db.execute(
                select(
                    func.sum(CookieTransaction.amount).filter(CookieTransaction.txn_type == "earn").label("earned"),
                    func.sum(func.abs(CookieTransaction.amount)).filter(CookieTransaction.txn_type == "spend").label("spent"),
                    func.sum(CookieTransaction.amount).filter(CookieTransaction.txn_type == "adjust").label("adjusted"),
                    func.count().label("txn_count"),
                )
                .where(
                    CookieTransaction.user_id == account.user_id,
                    CookieTransaction.created_at >= day_start,
                    CookieTransaction.created_at <= day_end,
                )
            )
            ds = day_stats.one()

            ledger = CookieLedger(
                snapshot_date=snapshot_date,
                user_id=account.user_id,
                account_id=account.id,
                opening_balance=opening,
                total_earned=ds.earned or Decimal("0"),
                total_spent=ds.spent or Decimal("0"),
                total_adjusted=ds.adjusted or Decimal("0"),
                closing_balance=account.balance,
                transaction_count=ds.txn_count or 0,
            )
            self.db.add(ledger)
            count += 1

        await self.db.flush()
        logger.info(f"[Cookie] Daily ledger created for {snapshot_date}: {count} records")
        return count


# ============================================================
# 3.2 自定义异常定义
# ============================================================
# 建议放在 app/exceptions.py

class InsufficientBalanceException(Exception):
    """余额不足异常"""
    def __init__(self, current_balance: Decimal, required_amount: Decimal, message: str = None):
        self.current_balance = current_balance
        self.required_amount = required_amount
        self.message = message or f"余额不足: 需要 {required_amount}, 当前 {current_balance}"
        super().__init__(self.message)


class AccountFrozenException(Exception):
    """账户冻结异常"""
    def __init__(self, message: str = "账户已被冻结"):
        self.message = message
        super().__init__(self.message)


class AccountNotFoundException(Exception):
    """账户不存在"""
    pass


class InvalidTransactionException(Exception):
    """无效交易"""
    pass
```



---

## 4. 定价计算引擎 — PricingEngine

> 文件路径建议: `app/services/pricing_engine.py`

```python
"""
CygnusX Cookie (饼干) 积分系统 — 定价计算引擎

支持动态定价策略：
1. 从数据库加载当前生效的定价策略（支持时段、优先级覆盖）
2. 根据流程分类和资源使用量计算费用明细
3. 支持缓存（Redis）加速频繁查询
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict

from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CookiePricing
from app.schemas.cookie import (
    CostBreakdown, CostBreakdownItem, BillingItem,
    TaskResourceRequest, FlowCategory
)
from app.core.redis import redis_client  # Redis 缓存客户端

logger = logging.getLogger(__name__)

# 缓存配置
PRICING_CACHE_KEY = "cookie:pricing:active"
PRICING_CACHE_TTL = 300  # 5分钟


# ============================================================
# 4.1 内部数据结构
# ============================================================

@dataclass
class PricingRule:
    """内存中的定价规则"""
    pricing_type: str
    resource_type: Optional[str]
    flow_category: Optional[str]
    base_cost: Decimal
    unit: str
    priority: int
    is_active: bool

    def calculate(self, quantity: Decimal) -> Decimal:
        """根据用量计算费用"""
        return (self.base_cost * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ============================================================
# 4.2 PricingEngine 主类
# ============================================================

class PricingEngine:
    """
    定价计算引擎

    使用方式:
        engine = PricingEngine(db)
        cost = await engine.calculate_task_cost("rna_seq", cores=8, memory_gb=32, estimated_hours=2.5)
        # cost.total = 总费用
        # cost.items = 费用拆分明细
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._rules_cache: Optional[List[PricingRule]] = None
        self._cache_time: Optional[datetime] = None

    # ──────────────────────────────────────────
    # 4.2.1 加载定价规则
    # ──────────────────────────────────────────

    async def load_active_rules(self, force_refresh: bool = False) -> List[PricingRule]:
        """
        加载当前生效的定价规则（带内存缓存 + Redis缓存）

        Args:
            force_refresh: 强制刷新缓存
        """
        # 内存缓存（5分钟内有效）
        if not force_refresh and self._rules_cache is not None:
            if self._cache_time and (datetime.utcnow() - self._cache_time).seconds < PRICING_CACHE_TTL:
                return self._rules_cache

        # Redis缓存
        if not force_refresh:
            cached = await redis_client.get(PRICING_CACHE_KEY)
            if cached:
                # 可以从Redis反序列化... 简化处理直接查DB
                pass

        # 数据库查询
        now = datetime.utcnow()
        result = await self.db.execute(
            select(CookiePricing)
            .where(
                and_(
                    CookiePricing.is_active == True,
                    CookiePricing.effective_from <= now,
                    or_(
                        CookiePricing.effective_until.is_(None),
                        CookiePricing.effective_until > now
                    )
                )
            )
            .order_by(desc(CookiePricing.priority))
        )
        rows = result.scalars().all()

        rules = []
        for row in rows:
            rules.append(PricingRule(
                pricing_type=row.pricing_type,
                resource_type=row.resource_type,
                flow_category=row.flow_category,
                base_cost=row.base_cost,
                unit=row.unit,
                priority=row.priority,
                is_active=row.is_active,
            ))

        self._rules_cache = rules
        self._cache_time = datetime.utcnow()
        logger.debug(f"[PricingEngine] Loaded {len(rules)} active pricing rules")
        return rules

    async def clear_cache(self):
        """清除缓存（定价策略变更后调用）"""
        self._rules_cache = None
        self._cache_time = None
        await redis_client.delete(PRICING_CACHE_KEY)
        logger.info("[PricingEngine] Cache cleared")

    # ──────────────────────────────────────────
    # 4.2.2 查询特定定价规则
    # ──────────────────────────────────────────

    async def get_rule(
        self,
        flow_category: str,
        resource_type: Optional[str] = None,
        pricing_type: str = "task_type"
    ) -> Optional[PricingRule]:
        """
        查询特定定价规则（按优先级匹配）

        匹配优先级:
        1. pricing_type + flow_category + resource_type (精确匹配)
        2. pricing_type + flow_category + None (分类通用)
        3. pricing_type + None + resource_type (资源通用)
        """
        rules = await self.load_active_rules()

        # 按优先级排序后匹配
        for rule in rules:
            if rule.pricing_type != pricing_type:
                continue
            fc_match = rule.flow_category == flow_category or rule.flow_category is None
            rt_match = rule.resource_type == resource_type or rule.resource_type is None
            if fc_match and rt_match:
                return rule

        return None

    async def get_rules_for_flow(
        self,
        flow_category: str,
        pricing_type: str = "task_type"
    ) -> List[PricingRule]:
        """获取指定流程分类的所有定价规则"""
        rules = await self.load_active_rules()
        return [
            r for r in rules
            if r.pricing_type == pricing_type
            and (r.flow_category == flow_category or r.flow_category is None)
        ]

    # ──────────────────────────────────────────
    # 4.2.3 计算任务费用明细
    # ──────────────────────────────────────────

    async def calculate_task_cost(
        self,
        flow_category: str,
        cores: int,
        memory_gb: float,
        estimated_hours: float
    ) -> CostBreakdown:
        """
        计算任务费用明细

        计费项:
        - base_fee: 基础费用（每个任务固定）
        - cpu_cost: CPU核时费用 = cores * hours * cpu_rate
        - memory_cost: 内存GB时费用 = memory_gb * hours * memory_rate

        Args:
            flow_category: 流程分类 (rna_seq / atac_seq / scrna_seq / ...)
            cores: CPU核数
            memory_gb: 内存GB
            estimated_hours: 预估执行小时数

        Returns:
            CostBreakdown: 费用拆分
        """
        items: List[CostBreakdownItem] = []
        hours = Decimal(str(estimated_hours))
        cores_d = Decimal(str(cores))
        memory_d = Decimal(str(memory_gb))

        # 1. 基础费用
        base_rule = await self.get_rule(flow_category, "base_fee")
        if base_rule:
            base_cost = base_rule.calculate(Decimal("1"))
            items.append(CostBreakdownItem(
                billing_item=BillingItem.TASK_BASE,
                item_name="基础费用",
                quantity=Decimal("1"),
                quantity_unit="task",
                unit_price=base_rule.base_cost,
                total_cost=base_cost,
            ))

        # 2. CPU核时费用
        cpu_hours = cores_d * hours
        cpu_rule = await self.get_rule(flow_category, "cpu_core_per_hour")
        if cpu_rule:
            cpu_cost = cpu_rule.calculate(cpu_hours)
            items.append(CostBreakdownItem(
                billing_item=BillingItem.CPU_USAGE,
                item_name="CPU使用费",
                quantity=cpu_hours.quantize(Decimal("0.01")),
                quantity_unit="core·hour",
                unit_price=cpu_rule.base_cost,
                total_cost=cpu_cost,
            ))

        # 3. 内存GB时费用
        mem_hours = memory_d * hours
        mem_rule = await self.get_rule(flow_category, "memory_gb_per_hour")
        if mem_rule:
            mem_cost = mem_rule.calculate(mem_hours)
            items.append(CostBreakdownItem(
                billing_item=BillingItem.MEMORY_USAGE,
                item_name="内存使用费",
                quantity=mem_hours.quantize(Decimal("0.01")),
                quantity_unit="GB·hour",
                unit_price=mem_rule.base_cost,
                total_cost=mem_cost,
            ))

        total = sum(item.total_cost for item in items)
        return CostBreakdown(items=items, total=total)

    # ──────────────────────────────────────────
    # 4.2.4 计算沙盒会话费用
    # ──────────────────────────────────────────

    async def calculate_sandbox_cost(
        self,
        session_duration_seconds: int,
        cores: int,
        memory_gb: float
    ) -> CostBreakdown:
        """
        计算沙盒会话费用

        计费项:
        - session_base: 会话基础费用（按小时）
        - cpu_cost: CPU核时费用
        - memory_cost: 内存GB时费用

        Args:
            session_duration_seconds: 会话时长（秒）
            cores: CPU核数
            memory_gb: 内存GB
        """
        items: List[CostBreakdownItem] = []
        hours = Decimal(str(session_duration_seconds)) / Decimal("3600")
        hours = hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cores_d = Decimal(str(cores))
        memory_d = Decimal(str(memory_gb))

        flow_category = "sandbox"

        # 1. 会话基础费用（按小时）
        session_rule = await self.get_rule(flow_category, "base_fee", "sandbox")
        if session_rule:
            session_cost = session_rule.calculate(hours)
            items.append(CostBreakdownItem(
                billing_item=BillingItem.SANDBOX_SESSION,
                item_name="沙盒会话费",
                quantity=hours,
                quantity_unit="hour",
                unit_price=session_rule.base_cost,
                total_cost=session_cost,
            ))

        # 2. CPU核时
        cpu_hours = cores_d * hours
        cpu_rule = await self.get_rule(flow_category, "cpu_core_per_hour", "sandbox")
        if cpu_rule:
            cpu_cost = cpu_rule.calculate(cpu_hours)
            items.append(CostBreakdownItem(
                billing_item=BillingItem.SANDBOX_CPU,
                item_name="沙盒CPU使用费",
                quantity=cpu_hours.quantize(Decimal("0.01")),
                quantity_unit="core·hour",
                unit_price=cpu_rule.base_cost,
                total_cost=cpu_cost,
            ))

        # 3. 内存GB时
        mem_hours = memory_d * hours
        mem_rule = await self.get_rule(flow_category, "memory_gb_per_hour", "sandbox")
        if mem_rule:
            mem_cost = mem_rule.calculate(mem_hours)
            items.append(CostBreakdownItem(
                billing_item=BillingItem.SANDBOX_MEMORY,
                item_name="沙盒内存使用费",
                quantity=mem_hours.quantize(Decimal("0.01")),
                quantity_unit="GB·hour",
                unit_price=mem_rule.base_cost,
                total_cost=mem_cost,
            ))

        total = sum(item.total_cost for item in items)
        return CostBreakdown(items=items, total=total)

    # ──────────────────────────────────────────
    # 4.2.5 根据实际执行时长计算真实费用
    # ──────────────────────────────────────────

    async def calculate_actual_cost(
        self,
        flow_category: str,
        started_at: datetime,
        completed_at: datetime,
        cores: int,
        memory_gb: float
    ) -> CostBreakdown:
        """
        根据实际执行时长计算真实费用（任务完成后调用）

        Args:
            flow_category: 流程分类
            started_at: 开始时间
            completed_at: 结束时间
            cores: 实际使用核数
            memory_gb: 实际使用内存
        """
        duration = completed_at - started_at
        hours = duration.total_seconds() / 3600.0
        hours = max(hours, 0.01)  # 最少按0.01小时计费

        return await self.calculate_task_cost(
            flow_category=flow_category,
            cores=cores,
            memory_gb=memory_gb,
            estimated_hours=hours
        )

    # ──────────────────────────────────────────
    # 4.2.6 快速费用估算（无需DB查询的缓存版本）
    # ──────────────────────────────────────────

    async def quick_estimate(
        self,
        flow_category: str,
        cores: int,
        memory_gb: float,
        estimated_hours: float
    ) -> Decimal:
        """
        快速费用估算（返回总费用数字）

        用于任务提交前的快速检查，比 calculate_task_cost 更快
        """
        rules = await self.load_active_rules()

        total = Decimal("0")
        hours = Decimal(str(estimated_hours))

        for rule in rules:
            if rule.flow_category != flow_category and rule.flow_category is not None:
                continue

            if rule.resource_type == "base_fee":
                total += rule.calculate(Decimal("1"))
            elif rule.resource_type == "cpu_core_per_hour":
                total += rule.calculate(Decimal(str(cores)) * hours)
            elif rule.resource_type == "memory_gb_per_hour":
                total += rule.calculate(Decimal(str(memory_gb)) * hours)

        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ──────────────────────────────────────────
    # 4.2.7 批量获取定价（用于展示）
    # ──────────────────────────────────────────

    async def get_all_active_pricing(self) -> List[Dict]:
        """获取所有生效的定价策略（用户查看定价页）"""
        rules = await self.load_active_rules()

        # 按 flow_category 分组
        grouped: Dict[str, List] = {}
        for rule in rules:
            fc = rule.flow_category or "通用"
            if fc not in grouped:
                grouped[fc] = []
            grouped[fc].append({
                "resource_type": rule.resource_type,
                "base_cost": float(rule.base_cost),
                "unit": rule.unit,
            })

        result = []
        for fc, items in grouped.items():
            result.append({
                "flow_category": fc,
                "items": items,
            })

        return result
```



---

## 5. 消费拦截器与系统集成

> 文件路径建议:
> - `app/middleware/cookie_middleware.py` — 中间件
> - `app/services/task_cookie_consumer.py` — 任务饼干消费者
> - `app/services/sandbox_cookie_consumer.py` — 沙盒饼干消费者

### 5.1 CookieRequiredMiddleware — 任务提交前检查

```python
"""
饼干消费拦截中间件

在任务提交API中自动检查余额:
- 余额不足返回 402 Payment Required
- 账户冻结返回 403 Forbidden
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable, Optional

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.services.cookie_service import CookieService
from app.services.pricing_engine import PricingEngine
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ============================================================
# 5.1.1 需要检查饼干的路径配置
# ============================================================

COOKIE_CHECK_PATHS = {
    # 路径前缀 -> 检查逻辑
    "/api/v1/tasks": {
        "method": "POST",
        "cost_extractor": "task_cost",  # 使用任务参数提取费用
    },
    "/api/v1/sandbox/sessions": {
        "method": "POST",
        "cost_extractor": "sandbox_base_cost",
    },
    "/api/v1/sandbox/execute": {
        "method": "POST", 
        "cost_extractor": "sandbox_execution_cost",
    },
}


class CookieRequiredMiddleware(BaseHTTPMiddleware):
    """
    任务提交前的饼干检查中间件

    挂在任务提交和沙盒启动的API路径上，自动:
    1. 从请求体中提取任务参数
    2. 调用PricingEngine估算费用
    3. 调用CookieService检查余额
    4. 余额不足返回 402
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 只处理配置的路径
        path_match = None
        for prefix, config in COOKIE_CHECK_PATHS.items():
            if request.url.path.startswith(prefix) and request.method == config["method"]:
                path_match = config
                break

        if path_match is None:
            return await call_next(request)

        # 获取当前用户
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail="未认证")

        user_id = user.get("id")
        if not user_id:
            return await call_next(request)

        # 管理员免检查
        if user.get("role") == "admin":
            return await call_next(request)

        # 读取请求体估算费用
        try:
            body = await request.body()
            if body:
                import json
                request_data = json.loads(body)
            else:
                request_data = {}
        except Exception:
            request_data = {}

        # 恢复请求体（FastAPI需要再次读取）
        async def receive():
            return {"type": "http.request", "body": body}
        request._receive = receive

        # 检查饼干余额
        async with AsyncSessionLocal() as db:
            cookie_service = CookieService(db)
            pricing_engine = PricingEngine(db)

            try:
                # 估算费用
                estimated_cost = await self._estimate_cost(
                    path_match["cost_extractor"],
                    request_data,
                    pricing_engine
                )

                if estimated_cost is None or estimated_cost <= 0:
                    return await call_next(request)

                # 检查余额
                has_enough = await cookie_service.check_balance(user_id, estimated_cost)

                if not has_enough:
                    balance = await cookie_service.get_balance(user_id)
                    logger.warning(
                        f"[CookieMiddleware] 余额不足 user={user_id} "
                        f"need={estimated_cost} have={balance}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail={
                            "error": "insufficient_balance",
                            "message": "饼干余额不足，无法提交任务",
                            "current_balance": float(balance),
                            "required_amount": float(estimated_cost),
                            "suggestion": "请联系管理员充值饼干"
                        }
                    )

                # 将预估费用存入请求状态，后续API处理可用
                request.state.estimated_cost = estimated_cost

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[CookieMiddleware] 检查余额异常: {e}")
                # 余额检查异常不阻止操作（降级策略）

        return await call_next(request)

    async def _estimate_cost(
        self,
        extractor_type: str,
        request_data: dict,
        pricing_engine: PricingEngine
    ) -> Optional[Decimal]:
        """根据请求数据估算费用"""
        if extractor_type == "task_cost":
            flow = request_data.get("flow_definition_id", "unknown")
            resources = request_data.get("resources", {})
            cores = resources.get("cores", 4)
            memory_gb = resources.get("memory", 16)
            runtime = resources.get("runtime", 2)  # hours
            return await pricing_engine.quick_estimate(flow, cores, memory_gb, runtime)

        elif extractor_type == "sandbox_base_cost":
            # 沙盒启动：预估1小时
            cores = request_data.get("cores", 2)
            memory_gb = request_data.get("memory_gb", 8)
            return await pricing_engine.quick_estimate("sandbox", cores, memory_gb, 1.0)

        elif extractor_type == "sandbox_execution_cost":
            # 沙盒执行：按10分钟预估
            cores = request_data.get("cores", 2)
            memory_gb = request_data.get("memory_gb", 8)
            return await pricing_engine.quick_estimate("sandbox", cores, memory_gb, 0.17)

        return None
```

---

### 5.2 TaskCookieConsumer — 任务饼干消费者

```python
"""
任务饼干消费者 — Celery任务完成后扣费

集成点:
- 任务提交成功: 预扣预估费用
- 任务完成: 根据实际执行时长多退少补
- 任务失败/取消: 退还预扣费用
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from celery import shared_task, Task
from celery.signals import task_postrun, task_prerun

from app.core.database import AsyncSessionLocal
from app.services.cookie_service import CookieService
from app.services.pricing_engine import PricingEngine
from app.services.consumption_logger import ConsumptionLogger

logger = logging.getLogger(__name__)

# ============================================================
# 5.2.1 Celery 信号集成（任务生命周期钩子）
# ============================================================

@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, task=None, kwargs=None, **extras):
    """
    Celery 任务开始前: 预扣预估饼干
    
    注意: task_prerun 是同步信号，需要用线程池执行异步操作
    """
    if not task_id or not kwargs:
        return

    task_name = task.name if task else "unknown"
    flow_definition_id = kwargs.get("flow_definition_id", "unknown")

    # 只处理 Snakemake 任务
    if "snakemake" not in task_name.lower() and "pipeline" not in task_name.lower():
        return

    user_id = kwargs.get("user_id")
    resources = kwargs.get("resources", {})

    if not user_id:
        return

    # 异步预扣（使用 Celery 子任务）
    prefreeze_cookie_task.delay(
        user_id=user_id,
        task_id=task_id,
        flow_definition_id=flow_definition_id,
        resources=resources,
    )


@task_postrun.connect
def on_task_postrun(sender=None, task_id=None, task=None, retval=None, state=None, **extras):
    """
    Celery 任务结束后: 根据实际执行时长结算
    
    state 可能值: SUCCESS / FAILURE / RETRY / REVOKED
    """
    if not task_id:
        return

    task_name = task.name if task else "unknown"

    if "snakemake" not in task_name.lower() and "pipeline" not in task_name.lower():
        return

    if state == "SUCCESS":
        # 任务成功：结算实际费用
        settle_cookie_task.delay(task_id=task_id, success=True)
    elif state in ("FAILURE", "REVOKED"):
        # 任务失败/取消：退还预扣
        settle_cookie_task.delay(task_id=task_id, success=False)


# ============================================================
# 5.2.2 Celery 任务定义
# ============================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def prefreeze_cookie_task(
    self,
    user_id: int,
    task_id: str,
    flow_definition_id: str,
    resources: dict,
):
    """
    预扣饼干任务
    
    在 Snakemake 任务开始前调用，冻结预估费用
    """
    import asyncio

    async def _prefreeze():
        async with AsyncSessionLocal() as db:
            cookie_service = CookieService(db)
            pricing_engine = PricingEngine(db)

            try:
                # 估算费用
                cores = resources.get("cores", 4)
                memory_gb = resources.get("memory", 16)
                runtime_hours = resources.get("runtime", 2)

                cost_breakdown = await pricing_engine.calculate_task_cost(
                    flow_category=flow_definition_id,
                    cores=cores,
                    memory_gb=memory_gb,
                    estimated_hours=runtime_hours,
                )
                estimated_cost = cost_breakdown.total

                if estimated_cost <= 0:
                    return {"status": "skipped", "reason": "no_cost"}

                # 预扣
                txn = await cookie_service.prefreeze(
                    user_id=user_id,
                    amount=estimated_cost,
                    source_type="task",
                    source_id=task_id,
                    description=f"任务预扣: {flow_definition_id} 预估 {runtime_hours}h",
                )

                # 记录消费明细
                for item in cost_breakdown.items:
                    await cookie_service.log_consumption(
                        user_id=user_id,
                        billing_item=item.billing_item,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        total_cost=item.total_cost,
                        task_id=task_id,
                        transaction_id=txn.id,
                    )

                await db.commit()

                return {
                    "status": "success",
                    "prefreeze_txn_id": txn.id,
                    "prefreeze_amount": float(estimated_cost),
                }

            except Exception as e:
                await db.rollback()
                logger.error(f"[Prefreeze] 预扣失败 task={task_id}: {e}")
                raise self.retry(exc=e)

    return asyncio.run(_prefreeze())


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def settle_cookie_task(self, task_id: str, success: bool):
    """
    结算饼干任务
    
    任务完成后调用，根据实际执行时长多退少补
    """
    import asyncio

    async def _settle():
        async with AsyncSessionLocal() as db:
            cookie_service = CookieService(db)

            try:
                # 查询该任务的预扣记录
                from sqlalchemy import select
                from app.models import CookieTransaction

                result = await db.execute(
                    select(CookieTransaction)
                    .where(
                        CookieTransaction.source_id == task_id,
                        CookieTransaction.txn_type == "freeze"
                    )
                    .order_by(CookieTransaction.created_at.desc())
                    .limit(1)
                )
                freeze_txn = result.scalar_one_or_none()

                if freeze_txn is None:
                    logger.warning(f"[Settle] 未找到预扣记录 task={task_id}")
                    return {"status": "skipped", "reason": "no_prefreeze_found"}

                prefreeze_amount = abs(freeze_txn.amount)
                user_id = freeze_txn.user_id

                if not success:
                    # 任务失败：全额退还
                    await cookie_service.cancel_prefreeze(
                        user_id=user_id,
                        source_id=task_id,
                        prefreeze_amount=prefreeze_amount,
                        reason="任务失败，退还预扣饼干",
                    )
                    await db.commit()
                    return {
                        "status": "refunded",
                        "refund_amount": float(prefreeze_amount),
                        "reason": "task_failed",
                    }

                # 任务成功：需要获取实际执行数据
                # 从 tasks 表查询实际执行信息
                from app.models import Task

                task_result = await db.execute(
                    select(Task).where(Task.task_id == task_id)
                )
                task_record = task_result.scalar_one_or_none()

                if task_record is None:
                    # 找不到任务记录，按预扣金额结算
                    actual_cost = prefreeze_amount
                else:
                    # 根据实际执行时长重新计算
                    pricing_engine = PricingEngine(db)

                    if task_record.started_at and task_record.completed_at:
                        resources = task_record.resources or {}
                        cost_breakdown = await pricing_engine.calculate_actual_cost(
                            flow_category=task_record.flow_definition_id,
                            started_at=task_record.started_at,
                            completed_at=task_record.completed_at,
                            cores=resources.get("cores", 4),
                            memory_gb=resources.get("memory", 16),
                        )
                        actual_cost = cost_breakdown.total
                    else:
                        actual_cost = prefreeze_amount

                # 结算
                txns = await cookie_service.settle(
                    user_id=user_id,
                    source_id=task_id,
                    actual_cost=actual_cost,
                    prefreeze_amount=prefreeze_amount,
                    description=f"任务结算: {task_id}",
                )

                await db.commit()

                refund = prefreeze_amount - actual_cost
                return {
                    "status": "settled",
                    "prefreeze_amount": float(prefreeze_amount),
                    "actual_cost": float(actual_cost),
                    "refund": float(refund),
                    "transactions": [t.id for t in txns],
                }

            except Exception as e:
                await db.rollback()
                logger.error(f"[Settle] 结算失败 task={task_id}: {e}")
                raise self.retry(exc=e)

    return asyncio.run(_settle())


# ============================================================
# 5.2.3 手动结算接口（API调用）
# ============================================================

async def manual_settle_task(
    task_id: str,
    user_id: int,
    started_at: datetime,
    completed_at: datetime,
    flow_definition_id: str,
    resources: dict,
    prefreeze_amount: Decimal,
    db_session,
):
    """
    手动结算接口（供API层直接调用，非Celery）

    使用场景: 任务完成回调中直接结算
    """
    cookie_service = CookieService(db_session)
    pricing_engine = PricingEngine(db_session)

    # 计算实际费用
    cost_breakdown = await pricing_engine.calculate_actual_cost(
        flow_category=flow_definition_id,
        started_at=started_at,
        completed_at=completed_at,
        cores=resources.get("cores", 4),
        memory_gb=resources.get("memory", 16),
    )
    actual_cost = cost_breakdown.total

    # 结算
    txns = await cookie_service.settle(
        user_id=user_id,
        source_id=task_id,
        actual_cost=actual_cost,
        prefreeze_amount=prefreeze_amount,
        description=f"任务结算: {flow_definition_id}",
    )

    # 记录消费明细
    for item in cost_breakdown.items:
        await cookie_service.log_consumption(
            user_id=user_id,
            billing_item=item.billing_item,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_cost=item.total_cost,
            task_id=task_id,
            started_at=started_at,
            ended_at=completed_at,
        )

    return {
        "prefreeze_amount": prefreeze_amount,
        "actual_cost": actual_cost,
        "refund": prefreeze_amount - actual_cost,
        "transactions": txns,
    }
```

---

### 5.3 SandboxCookieConsumer — 沙盒饼干消费者

```python
"""
沙盒饼干消费者

沙盒计费模式：
- 沙盒启动时: 检查余额，预扣1小时基础费用
- 沙盒运行中: 按分钟计费（后台定时任务每分钟检查）
- 沙盒关闭时: 结算最终费用
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from celery import shared_task
from celery.schedules import crontab

from app.core.database import AsyncSessionLocal
from app.services.cookie_service import CookieService
from app.services.pricing_engine import PricingEngine

logger = logging.getLogger(__name__)

# ============================================================
# 5.3.1 沙盒启动时扣费
# ============================================================

async def on_sandbox_start(
    user_id: int,
    session_id: str,
    cores: int,
    memory_gb: float,
    db_session
) -> dict:
    """
    沙盒启动时：检查余额 + 预扣基础费用

    Returns:
        {"success": bool, "prefreeze_txn_id": int|None, "message": str}
    """
    cookie_service = CookieService(db_session)
    pricing_engine = PricingEngine(db_session)

    # 预估1小时费用
    cost_breakdown = await pricing_engine.calculate_sandbox_cost(
        session_duration_seconds=3600,  # 1小时
        cores=cores,
        memory_gb=memory_gb,
    )
    estimated_cost = cost_breakdown.total

    if estimated_cost <= 0:
        return {"success": True, "prefreeze_txn_id": None, "message": "免费沙盒"}

    try:
        txn = await cookie_service.prefreeze(
            user_id=user_id,
            amount=estimated_cost,
            source_type="sandbox",
            source_id=session_id,
            description=f"沙盒预扣: {session_id} 预估1小时",
        )

        # 记录消费明细
        for item in cost_breakdown.items:
            await cookie_service.log_consumption(
                user_id=user_id,
                billing_item=item.billing_item,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_cost=item.total_cost,
                sandbox_session_id=session_id,
                transaction_id=txn.id,
            )

        return {
            "success": True,
            "prefreeze_txn_id": txn.id,
            "prefreeze_amount": estimated_cost,
            "message": f"预扣 {estimated_cost} 饼干",
        }

    except InsufficientBalanceException as e:
        return {
            "success": False,
            "prefreeze_txn_id": None,
            "message": str(e),
        }


# ============================================================
# 5.3.2 沙盒运行中 — 定时计费
# ============================================================

@shared_task
async def sandbox_billing_tick():
    """
    沙盒计费心跳 — Celery 定时任务，每分钟执行

    检查所有运行中的沙盒会话，按实际运行时长计费
    """
    async with AsyncSessionLocal() as db:
        cookie_service = CookieService(db)
        pricing_engine = PricingEngine(db)

        # 查询所有活跃沙盒会话
        from sqlalchemy import select
        from app.models import SandboxSession

        result = await db.execute(
            select(SandboxSession).where(SandboxSession.status == "running")
        )
        sessions = result.scalars().all()

        logger.debug(f"[SandboxBilling] Processing {len(sessions)} running sessions")

        for session in sessions:
            try:
                # 计算已运行时长
                if session.started_at is None:
                    continue

                elapsed = datetime.utcnow() - session.started_at
                elapsed_hours = elapsed.total_seconds() / 3600.0

                # 计算到当前时刻的总费用
                cost_breakdown = await pricing_engine.calculate_sandbox_cost(
                    session_duration_seconds=int(elapsed.total_seconds()),
                    cores=session.cores or 2,
                    memory_gb=session.memory_gb or 8.0,
                )
                total_cost = cost_breakdown.total

                # 检查是否需要扣费（每10分钟扣一次增量）
                last_billed = getattr(session, 'last_billed_at', None)
                if last_billed and (datetime.utcnow() - last_billed).seconds < 600:
                    continue

                # 记录增量消费
                increment = total_cost - Decimal(str(getattr(session, 'total_billed', 0) or 0))
                if increment > 0:
                    await cookie_service.log_consumption(
                        user_id=session.user_id,
                        billing_item=BillingItem.SANDBOX_SESSION,
                        quantity=elapsed_hours,
                        unit_price=Decimal("0"),  # 明细已在启动时记录
                        total_cost=increment,
                        sandbox_session_id=session.session_id,
                    )
                    session.last_billed_at = datetime.utcnow()
                    session.total_billed = float(total_cost)

            except Exception as e:
                logger.error(f"[SandboxBilling] 计费失败 session={session.session_id}: {e}")

        await db.commit()


# ============================================================
# 5.3.3 沙盒关闭时结算
# ============================================================

async def on_sandbox_end(
    user_id: int,
    session_id: str,
    started_at: datetime,
    ended_at: datetime,
    cores: int,
    memory_gb: float,
    prefreeze_amount: Decimal,
    db_session
) -> dict:
    """
    沙盒关闭时：结算最终费用

    流程:
    1. 计算实际总费用
    2. 解冻预扣
    3. 扣除实际费用
    4. 记录消费明细
    """
    cookie_service = CookieService(db_session)
    pricing_engine = PricingEngine(db_session)

    duration = ended_at - started_at
    duration_seconds = int(duration.total_seconds())

    # 计算实际费用
    cost_breakdown = await pricing_engine.calculate_sandbox_cost(
        session_duration_seconds=duration_seconds,
        cores=cores,
        memory_gb=memory_gb,
    )
    actual_cost = cost_breakdown.total

    # 结算（多退少补）
    txns = await cookie_service.settle(
        user_id=user_id,
        source_id=session_id,
        actual_cost=actual_cost,
        prefreeze_amount=prefreeze_amount,
        description=f"沙盒结算: {session_id} 实际运行 {duration_seconds}s",
    )

    # 记录最终消费明细
    for item in cost_breakdown.items:
        await cookie_service.log_consumption(
            user_id=user_id,
            billing_item=item.billing_item,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_cost=item.total_cost,
            sandbox_session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
        )

    refund = prefreeze_amount - actual_cost
    return {
        "prefreeze_amount": float(prefreeze_amount),
        "actual_cost": float(actual_cost),
        "refund": float(refund),
        "duration_seconds": duration_seconds,
        "transactions": [t.id for t in txns],
    }


# ============================================================
# 5.3.4 Celery Beat 定时配置
# ============================================================
# 在 celeryconfig.py 或 app/celery_app.py 中添加:
#
# beat_schedule = {
#     'sandbox-billing-tick': {
#         'task': 'app.services.sandbox_cookie_consumer.sandbox_billing_tick',
#         'schedule': 60.0,  # 每60秒
#     },
#     'daily-ledger-snapshot': {
#         'task': 'app.services.cookie_service.create_daily_ledger',
#         'schedule': crontab(hour=0, minute=5),  # 每天 00:05
#     },
# }
```



---

## 6. FastAPI 路由层

> 文件路径建议:
> - `app/api/v1/endpoints/cookies.py` — 用户端API
> - `app/api/v1/endpoints/admin_cookies.py` — 管理员端API

### 6.1 用户端 API — `/api/v1/cookies`

```python
"""
用户端饼干API — 查看账户、交易流水、定价、费用预估
"""
from __future__ import annotations

from typing import Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_active_user
from app.core.dependencies import get_current_active_user
from app.services.cookie_service import CookieService
from app.services.pricing_engine import PricingEngine
from app.schemas.cookie import (
    CookieAccountDTO, CookieTransactionDTO, PageModel,
    TransactionQueryParams, CostEstimateRequest, CostEstimateResponse,
    APIResponse, CookiePricingDTO, ConsumptionLogDTO
)
from app.exceptions import InsufficientBalanceException, AccountFrozenException

router = APIRouter(prefix="/cookies", tags=["饼干积分 (用户端)"])


# ============================================================
# 6.1.1 GET /api/v1/cookies/account — 获取我的饼干账户
# ============================================================

@router.get("/account", response_model=APIResponse)
async def get_my_account(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """获取当前用户的饼干账户信息"""
    cookie_service = CookieService(db)
    account = await cookie_service.get_or_create_account(current_user["id"])

    dto = CookieAccountDTO.model_validate(account)
    # 补充effective_balance计算
    dto.effective_balance = account.balance + account.frozen_balance

    return APIResponse(data=dto)


# ============================================================
# 6.1.2 GET /api/v1/cookies/transactions — 获取我的交易流水
# ============================================================

@router.get("/transactions", response_model=APIResponse)
async def get_my_transactions(
    txn_type: Optional[str] = None,
    source_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """
    获取当前用户的交易流水

    参数:
    - txn_type: earn/spend/adjust/refund/freeze/unfreeze
    - source_type: task/sandbox/admin/signup/daily/system
    - date_from/date_to: ISO格式日期时间
    - page/page_size: 分页
    """
    from datetime import datetime

    params = TransactionQueryParams(
        page=page,
        page_size=page_size,
        txn_type=txn_type,
        source_type=source_type,
        date_from=datetime.fromisoformat(date_from) if date_from else None,
        date_to=datetime.fromisoformat(date_to) if date_to else None,
    )

    cookie_service = CookieService(db)
    page_result = await cookie_service.get_transaction_history(
        user_id=current_user["id"],
        params=params,
    )

    return APIResponse(data=page_result)


# ============================================================
# 6.1.3 GET /api/v1/cookies/pricing — 获取当前定价策略（公开）
# ============================================================

@router.get("/pricing", response_model=APIResponse)
async def get_pricing(
    db: AsyncSession = Depends(get_db),
):
    """获取所有当前生效的定价策略（无需登录）"""
    pricing_engine = PricingEngine(db)
    pricing_data = await pricing_engine.get_all_active_pricing()

    return APIResponse(data=pricing_data)


# ============================================================
# 6.1.4 GET /api/v1/cookies/estimate — 预估任务饼干消耗
# ============================================================

@router.get("/estimate", response_model=APIResponse)
async def estimate_cost(
    flow_category: str,
    cores: int = 4,
    memory_gb: float = 16.0,
    estimated_hours: float = 2.0,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """
    预估任务饼干消耗（提交前调用）

    参数:
    - flow_category: 流程分类 (rna_seq / atac_seq / scrna_seq / sandbox)
    - cores: CPU核数 (1-128)
    - memory_gb: 内存GB (0.5-1024)
    - estimated_hours: 预估小时数 (0.01-720)
    """
    pricing_engine = PricingEngine(db)
    cookie_service = CookieService(db)

    # 计算费用
    cost_breakdown = await pricing_engine.calculate_task_cost(
        flow_category=flow_category,
        cores=cores,
        memory_gb=memory_gb,
        estimated_hours=estimated_hours,
    )

    # 检查余额
    current_balance = await cookie_service.get_balance(current_user["id"])
    has_sufficient = current_balance >= cost_breakdown.total

    response = CostEstimateResponse(
        flow_category=flow_category,
        has_sufficient_balance=has_sufficient,
        current_balance=current_balance,
        estimated_cost=cost_breakdown.total,
        breakdown=cost_breakdown.items,
        estimated_hours=estimated_hours,
    )

    return APIResponse(data=response)


# ============================================================
# 6.1.5 POST /api/v1/cookies/estimate — 预估（POST版本，支持更多参数）
# ============================================================

@router.post("/estimate", response_model=APIResponse)
async def estimate_cost_post(
    request: CostEstimateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """预估任务饼干消耗（POST版本，支持复杂参数）"""
    pricing_engine = PricingEngine(db)
    cookie_service = CookieService(db)

    resources = request.resources
    hours = resources.estimated_hours or 1.0

    cost_breakdown = await pricing_engine.calculate_task_cost(
        flow_category=request.flow_category,
        cores=resources.cores,
        memory_gb=resources.memory_gb,
        estimated_hours=hours,
    )

    current_balance = await cookie_service.get_balance(current_user["id"])

    response = CostEstimateResponse(
        flow_category=request.flow_category,
        has_sufficient_balance=current_balance >= cost_breakdown.total,
        current_balance=current_balance,
        estimated_cost=cost_breakdown.total,
        breakdown=cost_breakdown.items,
        estimated_hours=hours,
    )

    return APIResponse(data=response)


# ============================================================
# 6.1.6 GET /api/v1/cookies/balance-check — 快速余额检查
# ============================================================

@router.get("/balance-check", response_model=APIResponse)
async def quick_balance_check(
    required_amount: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """快速余额检查（前端轮询用）"""
    cookie_service = CookieService(db)
    balance = await cookie_service.get_balance(current_user["id"])

    result = {
        "balance": float(balance),
        "has_sufficient": True,
    }

    if required_amount is not None:
        result["has_sufficient"] = balance >= Decimal(str(required_amount))
        result["required_amount"] = required_amount
        result["deficit"] = float(max(Decimal("0"), Decimal(str(required_amount)) - balance))

    return APIResponse(data=result)
```

---

### 6.2 管理员端 API — `/api/v1/admin/cookies`

```python
"""
管理员端饼干API — 账户管理、充值扣减、定价策略、统计

权限要求: role = admin
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.services.cookie_service import CookieService
from app.services.pricing_engine import PricingEngine
from app.schemas.cookie import (
    APIResponse, CookieAccountDTO, CookieAccountListDTO,
    CookieTransactionDTO, PageModel, CookieAdjustRequest,
    CookieAdjustResponse, CookiePricingDTO, PricingCreateRequest,
    PricingUpdateRequest, AccountFreezeRequest, AccountUnfreezeRequest,
    CookieStatsResponse, AdminTransactionQueryParams, ConsumptionLogDTO,
    CookieStatsOverview
)
from app.models import CookiePricing

router = APIRouter(prefix="/admin/cookies", tags=["饼干积分 (管理员)"])


# ============================================================
# 6.2.1 GET /api/v1/admin/cookies/accounts — 查看所有账户
# ============================================================

@router.get("/accounts", response_model=APIResponse)
async def admin_list_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(balance|created_at|total_spent)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """查看所有用户饼干账户（支持搜索、筛选、排序）"""
    cookie_service = CookieService(db)
    page_result = await cookie_service.admin_get_all_accounts(
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(data=page_result)


# ============================================================
# 6.2.2 GET /api/v1/admin/cookies/accounts/{user_id} — 查看指定账户
# ============================================================

@router.get("/accounts/{user_id}", response_model=APIResponse)
async def admin_get_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """查看指定用户的饼干账户详情"""
    cookie_service = CookieService(db)
    account = await cookie_service.get_account_by_user(user_id)

    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    # 获取用户基本信息
    from sqlalchemy import select
    from app.models import User

    user_result = await db.execute(
        select(User.username, User.email).where(User.id == user_id)
    )
    user_row = user_result.one_or_none()

    dto = CookieAccountDTO.model_validate(account)
    dto.effective_balance = account.balance + account.frozen_balance

    # 获取最近10笔交易
    from app.schemas.cookie import TransactionQueryParams
    tx_page = await cookie_service.get_transaction_history(
        user_id=user_id,
        params=TransactionQueryParams(page=1, page_size=10),
    )

    return APIResponse(data={
        "account": dto,
        "user": {
            "id": user_id,
            "username": user_row.username if user_row else None,
            "email": user_row.email if user_row else None,
        },
        "recent_transactions": tx_page.items,
    })


# ============================================================
# 6.2.3 POST /api/v1/admin/cookies/adjust — 管理员调整余额
# ============================================================

@router.post("/adjust", response_model=APIResponse)
async def admin_adjust_balance(
    request: CookieAdjustRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """
    管理员调整用户饼干余额（充值/扣减）

    - amount > 0: 充值饼干给用户
    - amount < 0: 扣减用户的饼干
    """
    cookie_service = CookieService(db)

    try:
        result = await cookie_service.adjust(
            admin_id=admin["id"],
            user_id=request.user_id,
            amount=request.amount,
            reason=request.reason,
        )
        await db.commit()
        return APIResponse(data=result)

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# 6.2.4 PUT /api/v1/admin/cookies/accounts/{user_id}/freeze — 冻结账户
# ============================================================

@router.put("/accounts/{user_id}/freeze", response_model=APIResponse)
async def admin_freeze_account(
    user_id: int,
    request: AccountFreezeRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """冻结用户饼干账户"""
    cookie_service = CookieService(db)

    account = await cookie_service.freeze_account(
        user_id=user_id,
        reason=request.reason,
        admin_id=admin["id"],
    )
    await db.commit()

    return APIResponse(data={
        "user_id": user_id,
        "status": account.status,
        "frozen_reason": account.frozen_reason,
        "frozen_at": account.frozen_at,
    })


# ============================================================
# 6.2.5 PUT /api/v1/admin/cookies/accounts/{user_id}/unfreeze — 解冻账户
# ============================================================

@router.put("/accounts/{user_id}/unfreeze", response_model=APIResponse)
async def admin_unfreeze_account(
    user_id: int,
    request: AccountUnfreezeRequest = None,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """解冻用户饼干账户"""
    cookie_service = CookieService(db)

    account = await cookie_service.unfreeze_account(
        user_id=user_id,
        reason=request.reason if request else None,
    )
    await db.commit()

    return APIResponse(data={
        "user_id": user_id,
        "status": account.status,
        "unfrozen_at": datetime.utcnow(),
    })


# ============================================================
# 6.2.6 PUT /api/v1/admin/cookies/accounts/{user_id}/suspend — 停用账户
# ============================================================

@router.put("/accounts/{user_id}/suspend", response_model=APIResponse)
async def admin_suspend_account(
    user_id: int,
    request: AccountFreezeRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """停用用户饼干账户（更严厉，需要管理员才能恢复）"""
    cookie_service = CookieService(db)

    account = await cookie_service.suspend_account(
        user_id=user_id,
        reason=request.reason,
        admin_id=admin["id"],
    )
    await db.commit()

    return APIResponse(data={
        "user_id": user_id,
        "status": account.status,
        "suspended_reason": account.frozen_reason,
    })


# ============================================================
# 6.2.7 GET /api/v1/admin/cookies/transactions — 查看所有交易流水
# ============================================================

@router.get("/transactions", response_model=APIResponse)
async def admin_list_transactions(
    user_id: Optional[int] = None,
    txn_type: Optional[str] = None,
    source_type: Optional[str] = None,
    admin_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """查看所有交易流水（高级筛选）"""
    params = AdminTransactionQueryParams(
        page=page,
        page_size=page_size,
        user_id=user_id,
        txn_type=txn_type,
        source_type=source_type,
        admin_id=admin_id,
        date_from=datetime.fromisoformat(date_from) if date_from else None,
        date_to=datetime.fromisoformat(date_to) if date_to else None,
        min_amount=min_amount,
        max_amount=max_amount,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    cookie_service = CookieService(db)
    page_result = await cookie_service.admin_get_all_transactions(params)
    return APIResponse(data=page_result)


# ============================================================
# 6.2.8 GET /api/v1/admin/cookies/stats — 统计仪表盘
# ============================================================

@router.get("/stats", response_model=APIResponse)
async def admin_get_stats(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """饼干统计仪表盘数据"""
    cookie_service = CookieService(db)
    stats = await cookie_service.get_stats()
    return APIResponse(data=stats)


# ============================================================
# 6.2.9 GET /api/v1/admin/cookies/pricing — 查看定价策略
# ============================================================

@router.get("/pricing", response_model=APIResponse)
async def admin_list_pricing(
    flow_category: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """查看所有定价策略（管理员完整版）"""
    from sqlalchemy import select
    from sqlalchemy import desc as sa_desc

    query = select(CookiePricing)

    if flow_category:
        query = query.where(
            (CookiePricing.flow_category == flow_category) | (CookiePricing.flow_category.is_(None))
        )
    if is_active is not None:
        query = query.where(CookiePricing.is_active == is_active)

    query = query.order_by(sa_desc(CookiePricing.priority), CookiePricing.created_at.desc())

    result = await db.execute(query)
    items = result.scalars().all()

    return APIResponse(data=[CookiePricingDTO.model_validate(p) for p in items])


# ============================================================
# 6.2.10 POST /api/v1/admin/cookies/pricing — 新增定价策略
# ============================================================

@router.post("/pricing", response_model=APIResponse)
async def admin_create_pricing(
    request: PricingCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """新增定价策略"""
    pricing = CookiePricing(
        pricing_type=request.pricing_type.value,
        resource_type=request.resource_type.value if request.resource_type else None,
        flow_category=request.flow_category,
        base_cost=request.base_cost,
        unit=request.unit.value,
        effective_from=request.effective_from or datetime.utcnow(),
        effective_until=request.effective_until,
        priority=request.priority,
        description=request.description,
        created_by=admin["id"],
    )
    db.add(pricing)
    await db.flush()

    # 清除缓存
    pricing_engine = PricingEngine(db)
    await pricing_engine.clear_cache()

    await db.commit()

    return APIResponse(
        message="定价策略创建成功",
        data=CookiePricingDTO.model_validate(pricing),
    )


# ============================================================
# 6.2.11 PUT /api/v1/admin/cookies/pricing/{pricing_id} — 修改定价策略
# ============================================================

@router.put("/pricing/{pricing_id}", response_model=APIResponse)
async def admin_update_pricing(
    pricing_id: int,
    request: PricingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """修改定价策略"""
    from sqlalchemy import select

    result = await db.execute(
        select(CookiePricing).where(CookiePricing.id == pricing_id)
    )
    pricing = result.scalar_one_or_none()

    if pricing is None:
        raise HTTPException(status_code=404, detail="定价策略不存在")

    update_data = request.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if hasattr(pricing, field_name):
            setattr(pricing, field_name, value)

    pricing.updated_by = admin["id"]
    pricing.updated_at = datetime.utcnow()

    # 清除缓存
    pricing_engine = PricingEngine(db)
    await pricing_engine.clear_cache()

    await db.commit()

    return APIResponse(
        message="定价策略更新成功",
        data=CookiePricingDTO.model_validate(pricing),
    )


# ============================================================
# 6.2.12 DELETE /api/v1/admin/cookies/pricing/{pricing_id} — 禁用定价策略
# ============================================================

@router.delete("/pricing/{pricing_id}", response_model=APIResponse)
async def admin_delete_pricing(
    pricing_id: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """禁用定价策略（逻辑删除，设置 is_active = False）"""
    from sqlalchemy import select

    result = await db.execute(
        select(CookiePricing).where(CookiePricing.id == pricing_id)
    )
    pricing = result.scalar_one_or_none()

    if pricing is None:
        raise HTTPException(status_code=404, detail="定价策略不存在")

    pricing.is_active = False
    pricing.effective_until = datetime.utcnow()
    pricing.updated_by = admin["id"]

    # 清除缓存
    pricing_engine = PricingEngine(db)
    await pricing_engine.clear_cache()

    await db.commit()

    return APIResponse(message="定价策略已禁用")


# ============================================================
# 6.2.13 GET /api/v1/admin/cookies/consumption-logs — 消费明细查询
# ============================================================

@router.get("/consumption-logs", response_model=APIResponse)
async def admin_list_consumption_logs(
    user_id: Optional[int] = None,
    task_id: Optional[str] = None,
    sandbox_session_id: Optional[str] = None,
    billing_item: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """查看消费明细（对账用）"""
    from sqlalchemy import select, func, desc as sa_desc
    from app.models import CookieConsumptionLog

    query = select(CookieConsumptionLog)

    if user_id:
        query = query.where(CookieConsumptionLog.user_id == user_id)
    if task_id:
        query = query.where(CookieConsumptionLog.task_id == task_id)
    if sandbox_session_id:
        query = query.where(CookieConsumptionLog.sandbox_session_id == sandbox_session_id)
    if billing_item:
        query = query.where(CookieConsumptionLog.billing_item == billing_item)

    # 计数
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # 分页
    offset = (page - 1) * page_size
    query = query.order_by(sa_desc(CookieConsumptionLog.created_at)).offset(offset).limit(page_size)

    result = await db.execute(query)
    items = [ConsumptionLogDTO.model_validate(r) for r in result.scalars().all()]

    page_result = PageModel(
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
        items=items,
    )

    return APIResponse(data=page_result)


# ============================================================
# 6.2.14 POST /api/v1/admin/cookies/batch-adjust — 批量调整
# ============================================================

@router.post("/batch-adjust", response_model=APIResponse)
async def admin_batch_adjust(
    user_ids: list[int],
    amount: float,
    reason: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """
    批量调整多个用户的饼干余额（如全服补偿）

    参数:
    - user_ids: 用户ID列表
    - amount: 调整金额（正数=充值，负数=扣减）
    - reason: 调整原因
    """
    from decimal import Decimal

    cookie_service = CookieService(db)
    results = []
    errors = []

    for user_id in user_ids:
        try:
            result = await cookie_service.adjust(
                admin_id=admin["id"],
                user_id=user_id,
                amount=Decimal(str(amount)),
                reason=reason,
            )
            results.append({"user_id": user_id, "status": "success", "transaction_id": result.transaction_id})
        except Exception as e:
            errors.append({"user_id": user_id, "status": "failed", "error": str(e)})

    await db.commit()

    return APIResponse(data={
        "total": len(user_ids),
        "success": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    })


# ============================================================
# 6.2.15 GET /api/v1/admin/cookies/export — 导出交易流水
# ============================================================

@router.get("/export/transactions")
async def admin_export_transactions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    format: str = Query("csv", regex="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """导出交易流水（CSV或JSON）"""
    from fastapi.responses import StreamingResponse
    import csv
    import io
    from sqlalchemy import select, desc as sa_desc
    from app.models import CookieTransaction, User

    query = select(
        CookieTransaction,
        User.username.label("username"),
    ).join(User, CookieTransaction.user_id == User.id)

    if date_from:
        df = datetime.fromisoformat(date_from)
        query = query.where(CookieTransaction.created_at >= df)
    if date_to:
        dt = datetime.fromisoformat(date_to)
        query = query.where(CookieTransaction.created_at <= dt)

    query = query.order_by(sa_desc(CookieTransaction.created_at))

    result = await db.execute(query)
    rows = result.all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "User ID", "Username", "Type", "Amount",
            "Balance After", "Source Type", "Source ID",
            "Description", "Created At"
        ])

        for row in rows:
            txn, username = row
            writer.writerow([
                txn.id, txn.user_id, username, txn.txn_type,
                float(txn.amount), float(txn.balance_after),
                txn.source_type or "", txn.source_id or "",
                txn.description, txn.created_at.isoformat()
            ])

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cookie_transactions.csv"}
        )

    # JSON format
    data = []
    for row in rows:
        txn, username = row
        data.append({
            "id": txn.id,
            "user_id": txn.user_id,
            "username": username,
            "txn_type": txn.txn_type,
            "amount": float(txn.amount),
            "balance_after": float(txn.balance_after),
            "source_type": txn.source_type,
            "source_id": txn.source_id,
            "description": txn.description,
            "created_at": txn.created_at.isoformat(),
        })

    from fastapi.responses import JSONResponse
    return JSONResponse(content=data)
```



---

## 7. 默认定价策略数据

### 7.1 INSERT 语句

```sql
-- ============================================================
-- 7.1 任务类型定价
-- ============================================================

-- RNA-seq: 基础20饼干 + 每核时5饼干 + 每GB时1饼干
INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('task_type', 'base_fee', 'rna_seq', 20.0000, 'per_task', TRUE, 100, 'RNA-seq基础费用', 1),
    ('resource', 'cpu_core_per_hour', 'rna_seq', 5.0000, 'per_core_hour', TRUE, 100, 'RNA-seq CPU核时费用', 1),
    ('resource', 'memory_gb_per_hour', 'rna_seq', 1.0000, 'per_gb_hour', TRUE, 100, 'RNA-seq 内存GB时费用', 1);

-- ATAC-seq: 基础25饼干 + 每核时6饼干 + 每GB时1.5饼干
INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('task_type', 'base_fee', 'atac_seq', 25.0000, 'per_task', TRUE, 100, 'ATAC-seq基础费用', 1),
    ('resource', 'cpu_core_per_hour', 'atac_seq', 6.0000, 'per_core_hour', TRUE, 100, 'ATAC-seq CPU核时费用', 1),
    ('resource', 'memory_gb_per_hour', 'atac_seq', 1.5000, 'per_gb_hour', TRUE, 100, 'ATAC-seq 内存GB时费用', 1);

-- scRNA-seq: 基础30饼干 + 每核时8饼干 + 每GB时2饼干
INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('task_type', 'base_fee', 'scrna_seq', 30.0000, 'per_task', TRUE, 100, 'scRNA-seq基础费用', 1),
    ('resource', 'cpu_core_per_hour', 'scrna_seq', 8.0000, 'per_core_hour', TRUE, 100, 'scRNA-seq CPU核时费用', 1),
    ('resource', 'memory_gb_per_hour', 'scrna_seq', 2.0000, 'per_gb_hour', TRUE, 100, 'scRNA-seq 内存GB时费用', 1);

-- 通用任务（后备定价，当特定流程没有定价时使用）
INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('task_type', 'base_fee', NULL, 15.0000, 'per_task', TRUE, 0, '通用任务基础费用（后备）', 1),
    ('resource', 'cpu_core_per_hour', NULL, 4.0000, 'per_core_hour', TRUE, 0, '通用CPU核时费用（后备）', 1),
    ('resource', 'memory_gb_per_hour', NULL, 0.8000, 'per_gb_hour', TRUE, 0, '通用内存GB时费用（后备）', 1);


-- ============================================================
-- 7.2 沙盒定价
-- ============================================================

INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('sandbox', 'base_fee', 'sandbox', 5.0000, 'per_hour', TRUE, 100, '沙盒会话基础费用（每小时）', 1),
    ('sandbox', 'cpu_core_per_hour', 'sandbox', 3.0000, 'per_core_hour', TRUE, 100, '沙盒CPU核时费用', 1),
    ('sandbox', 'memory_gb_per_hour', 'sandbox', 0.5000, 'per_gb_hour', TRUE, 100, '沙盒内存GB时费用', 1);


-- ============================================================
-- 7.3 注册奖励
-- ============================================================

INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
VALUES
    ('bonus', NULL, 'signup', 100.0000, 'per_user', TRUE, 100, '新用户注册奖励100饼干', 1);
```

### 7.2 费用计算示例

```
费用计算示例:

1. RNA-seq 任务 (8核, 32GB, 运行2小时):
   基础费用:           1 x 20.00 =  20.00
   CPU费用:   8核 x 2h x 5.00  =  80.00
   内存费用: 32GB x 2h x 1.00  =  64.00
   --------------------------------------
   合计:                          164.00 饼干

2. ATAC-seq 任务 (16核, 64GB, 运行3小时):
   基础费用:           1 x 25.00 =  25.00
   CPU费用:  16核 x 3h x 6.00  = 288.00
   内存费用: 64GB x 3h x 1.50  = 288.00
   --------------------------------------
   合计:                          601.00 饼干

3. scRNA-seq 任务 (8核, 16GB, 运行1.5小时):
   基础费用:           1 x 30.00 =  30.00
   CPU费用:   8核 x 1.5h x 8.00 =  96.00
   内存费用: 16GB x 1.5h x 2.00 =  48.00
   --------------------------------------
   合计:                          174.00 饼干

4. 沙盒会话 (2核, 8GB, 使用30分钟):
   基础费用:          0.5h x 5.00 =   2.50
   CPU费用:  2核 x 0.5h x 3.00  =   3.00
   内存费用: 8GB x 0.5h x 0.50  =   2.00
   --------------------------------------
   合计:                            7.50 饼干

5. 新用户注册:
   注册奖励:                      100.00 饼干（免费获得）
```

---

## 8. 部署与迁移说明

### 8.1 Alembic 迁移脚本

```python
"""
Alembic 迁移脚本示例
文件: alembic/versions/20250101_add_cookie_system.py
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '20250101_add_cookie_system'
down_revision = 'xxxx_previous_revision'  # 替换为实际的上一版本
branch_labels = None
depends_on = None


def upgrade():
    # 1. 创建 cookie_accounts 表
    op.create_table(
        'cookie_accounts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('balance', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('frozen_balance', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('total_earned', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('total_spent', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('total_adjusted', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('frozen_reason', sa.Text(), nullable=True),
        sa.Column('frozen_by', sa.Integer(), nullable=True),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['frozen_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.CheckConstraint("status IN ('active', 'frozen', 'suspended')"),
    )

    # 2. 创建 cookie_transactions 表
    op.create_table(
        'cookie_transactions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('txn_type', sa.String(30), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=True),
        sa.Column('source_id', sa.String(100), nullable=True),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('adjust_reason', sa.Text(), nullable=True),
        sa.Column('task_type', sa.String(50), nullable=True),
        sa.Column('resource_cores', sa.Integer(), nullable=True),
        sa.Column('resource_memory_gb', sa.Numeric(6, 1), nullable=True),
        sa.Column('execution_seconds', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['account_id'], ['cookie_accounts.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "(txn_type NOT IN ('earn', 'adjust') OR amount >= 0) AND "
            "(txn_type NOT IN ('spend', 'freeze') OR amount <= 0)"
        ),
    )

    # 3. 创建 cookie_pricing 表
    op.create_table(
        'cookie_pricing',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pricing_type', sa.String(30), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('flow_category', sa.String(50), nullable=True),
        sa.Column('base_cost', sa.Numeric(10, 4), nullable=False),
        sa.Column('unit', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('effective_from', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("pricing_type IN ('task_type', 'resource', 'sandbox', 'bonus')"),
        sa.CheckConstraint("unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', 'per_session', 'per_user')"),
    )

    # 4. 创建 cookie_consumption_logs 表
    op.create_table(
        'cookie_consumption_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(100), nullable=True),
        sa.Column('sandbox_session_id', sa.String(100), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('billing_item', sa.String(50), nullable=False),
        sa.Column('quantity', sa.Numeric(10, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(10, 4), nullable=False),
        sa.Column('total_cost', sa.Numeric(10, 2), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['transaction_id'], ['cookie_transactions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "billing_item IN ('task_base', 'cpu_usage', 'memory_usage', "
            "'execution_time', 'sandbox_session', 'sandbox_cpu', 'sandbox_memory')"
        ),
    )

    # 5. 创建 cookie_ledger 表
    op.create_table(
        'cookie_ledger',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('opening_balance', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_earned', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('total_spent', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('total_adjusted', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('closing_balance', sa.Numeric(12, 2), nullable=False),
        sa.Column('transaction_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['account_id'], ['cookie_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_date', 'user_id'),
    )

    # 6. 创建索引
    op.create_index('idx_accounts_status', 'cookie_accounts', ['status'], postgresql_where=sa.text("status != 'active'"))
    op.create_index('idx_accounts_updated_at', 'cookie_accounts', ['updated_at'])

    op.create_index('idx_txn_user_created', 'cookie_transactions', ['user_id', sa.text('created_at DESC'), 'txn_type'], postgresql_include=['amount', 'balance_after', 'source_type', 'description'])
    op.create_index('idx_txn_source', 'cookie_transactions', ['source_type', 'source_id'], postgresql_where=sa.text('source_id IS NOT NULL'))
    op.create_index('idx_txn_type_created', 'cookie_transactions', ['txn_type', sa.text('created_at DESC')])
    op.create_index('idx_txn_account', 'cookie_transactions', ['account_id', sa.text('created_at DESC')])
    op.create_index('idx_txn_admin', 'cookie_transactions', ['admin_id', sa.text('created_at DESC')], postgresql_where=sa.text('admin_id IS NOT NULL'))

    op.create_index('idx_pricing_query', 'cookie_pricing', ['flow_category', 'resource_type', sa.text('priority DESC')], postgresql_where=sa.text("is_active = TRUE AND (effective_until IS NULL OR effective_until > NOW())"))
    op.create_index('idx_pricing_effective', 'cookie_pricing', ['effective_from', 'effective_until'])

    op.create_index('idx_logs_task', 'cookie_consumption_logs', ['task_id'], postgresql_where=sa.text('task_id IS NOT NULL'))
    op.create_index('idx_logs_sandbox', 'cookie_consumption_logs', ['sandbox_session_id'], postgresql_where=sa.text('sandbox_session_id IS NOT NULL'))
    op.create_index('idx_logs_user_created', 'cookie_consumption_logs', ['user_id', sa.text('created_at DESC')])
    op.create_index('idx_logs_transaction', 'cookie_consumption_logs', ['transaction_id'])

    op.create_index('idx_ledger_date', 'cookie_ledger', [sa.text('snapshot_date DESC')])
    op.create_index('idx_ledger_user_date', 'cookie_ledger', ['user_id', sa.text('snapshot_date DESC')])

    # 7. 创建触发器函数
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_update_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_accounts_updated_at
            BEFORE UPDATE ON cookie_accounts
            FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();
    """)

    op.execute("""
        CREATE TRIGGER trg_pricing_updated_at
            BEFORE UPDATE ON cookie_pricing
            FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION fn_update_account_stats()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.txn_type = 'earn' THEN
                UPDATE cookie_accounts
                SET total_earned = total_earned + NEW.amount,
                    balance = balance + NEW.amount
                WHERE id = NEW.account_id;
            ELSIF NEW.txn_type = 'spend' OR NEW.txn_type = 'freeze' THEN
                UPDATE cookie_accounts
                SET total_spent = total_spent + ABS(NEW.amount),
                    balance = balance + NEW.amount
                WHERE id = NEW.account_id;
            ELSIF NEW.txn_type = 'adjust' THEN
                UPDATE cookie_accounts
                SET total_adjusted = total_adjusted + NEW.amount,
                    balance = balance + NEW.amount
                WHERE id = NEW.account_id;
            ELSIF NEW.txn_type = 'refund' OR NEW.txn_type = 'unfreeze' THEN
                UPDATE cookie_accounts
                SET balance = balance + NEW.amount
                WHERE id = NEW.account_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_transaction_insert
            AFTER INSERT ON cookie_transactions
            FOR EACH ROW EXECUTE FUNCTION fn_update_account_stats();
    """)

    # 8. 插入默认定价数据
    op.execute("""
        INSERT INTO cookie_pricing (pricing_type, resource_type, flow_category, base_cost, unit, is_active, priority, description, created_by)
        VALUES
            ('task_type', 'base_fee', 'rna_seq', 20.0000, 'per_task', TRUE, 100, 'RNA-seq基础费用', 1),
            ('resource', 'cpu_core_per_hour', 'rna_seq', 5.0000, 'per_core_hour', TRUE, 100, 'RNA-seq CPU核时费用', 1),
            ('resource', 'memory_gb_per_hour', 'rna_seq', 1.0000, 'per_gb_hour', TRUE, 100, 'RNA-seq 内存GB时费用', 1),
            ('task_type', 'base_fee', 'atac_seq', 25.0000, 'per_task', TRUE, 100, 'ATAC-seq基础费用', 1),
            ('resource', 'cpu_core_per_hour', 'atac_seq', 6.0000, 'per_core_hour', TRUE, 100, 'ATAC-seq CPU核时费用', 1),
            ('resource', 'memory_gb_per_hour', 'atac_seq', 1.5000, 'per_gb_hour', TRUE, 100, 'ATAC-seq 内存GB时费用', 1),
            ('task_type', 'base_fee', 'scrna_seq', 30.0000, 'per_task', TRUE, 100, 'scRNA-seq基础费用', 1),
            ('resource', 'cpu_core_per_hour', 'scrna_seq', 8.0000, 'per_core_hour', TRUE, 100, 'scRNA-seq CPU核时费用', 1),
            ('resource', 'memory_gb_per_hour', 'scrna_seq', 2.0000, 'per_gb_hour', TRUE, 100, 'scRNA-seq 内存GB时费用', 1),
            ('task_type', 'base_fee', NULL, 15.0000, 'per_task', TRUE, 0, '通用任务基础费用（后备）', 1),
            ('resource', 'cpu_core_per_hour', NULL, 4.0000, 'per_core_hour', TRUE, 0, '通用CPU核时费用（后备）', 1),
            ('resource', 'memory_gb_per_hour', NULL, 0.8000, 'per_gb_hour', TRUE, 0, '通用内存GB时费用（后备）', 1),
            ('sandbox', 'base_fee', 'sandbox', 5.0000, 'per_hour', TRUE, 100, '沙盒会话基础费用（每小时）', 1),
            ('sandbox', 'cpu_core_per_hour', 'sandbox', 3.0000, 'per_core_hour', TRUE, 100, '沙盒CPU核时费用', 1),
            ('sandbox', 'memory_gb_per_hour', 'sandbox', 0.5000, 'per_gb_hour', TRUE, 100, '沙盒内存GB时费用', 1),
            ('bonus', NULL, 'signup', 100.0000, 'per_user', TRUE, 100, '新用户注册奖励100饼干', 1);
    """)


def downgrade():
    # 删除顺序与创建相反
    op.drop_index('idx_ledger_user_date', table_name='cookie_ledger')
    op.drop_index('idx_ledger_date', table_name='cookie_ledger')
    op.drop_index('idx_logs_transaction', table_name='cookie_consumption_logs')
    op.drop_index('idx_logs_user_created', table_name='cookie_consumption_logs')
    op.drop_index('idx_logs_sandbox', table_name='cookie_consumption_logs')
    op.drop_index('idx_logs_task', table_name='cookie_consumption_logs')
    op.drop_index('idx_pricing_effective', table_name='cookie_pricing')
    op.drop_index('idx_pricing_query', table_name='cookie_pricing')
    op.drop_index('idx_txn_admin', table_name='cookie_transactions')
    op.drop_index('idx_txn_account', table_name='cookie_transactions')
    op.drop_index('idx_txn_type_created', table_name='cookie_transactions')
    op.drop_index('idx_txn_source', table_name='cookie_transactions')
    op.drop_index('idx_txn_user_created', table_name='cookie_transactions')
    op.drop_index('idx_accounts_updated_at', table_name='cookie_accounts')
    op.drop_index('idx_accounts_status', table_name='cookie_accounts')

    op.drop_table('cookie_ledger')
    op.drop_table('cookie_consumption_logs')
    op.drop_table('cookie_pricing')
    op.drop_table('cookie_transactions')
    op.drop_table('cookie_accounts')

    op.execute("DROP FUNCTION IF EXISTS fn_update_account_stats()")
    op.execute("DROP FUNCTION IF EXISTS fn_update_timestamp()")
```

### 8.2 SQLAlchemy ORM 模型

```python
"""
SQLAlchemy ORM 模型定义
文件: app/models/cookie.py
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    Column, Integer, BigInteger, String, Numeric,
    Boolean, DateTime, Date, Text, ForeignKey, CheckConstraint, UniqueConstraint,
    func
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import INET

from app.core.database import Base


class CookieAccount(Base):
    __tablename__ = "cookie_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    balance = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    frozen_balance = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    total_earned = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_spent = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_adjusted = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    status = Column(String(20), nullable=False, default="active")
    frozen_reason = Column(Text, nullable=True)
    frozen_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    frozen_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="cookie_account")
    transactions = relationship("CookieTransaction", back_populates="account", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'frozen', 'suspended')"),
    )


class CookieTransaction(Base):
    __tablename__ = "cookie_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey("cookie_accounts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    txn_type = Column(String(30), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)

    source_type = Column(String(30), nullable=True)
    source_id = Column(String(100), nullable=True)

    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    adjust_reason = Column(Text, nullable=True)

    task_type = Column(String(50), nullable=True)
    resource_cores = Column(Integer, nullable=True)
    resource_memory_gb = Column(Numeric(6, 1), nullable=True)
    execution_seconds = Column(Integer, nullable=True)

    description = Column(Text, nullable=False)
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    account = relationship("CookieAccount", foreign_keys=[account_id], back_populates="transactions")

    __table_args__ = (
        CheckConstraint(
            "(txn_type NOT IN ('earn', 'adjust') OR amount >= 0) AND "
            "(txn_type NOT IN ('spend', 'freeze') OR amount <= 0)"
        ),
    )


class CookiePricing(Base):
    __tablename__ = "cookie_pricing"

    id = Column(Integer, primary_key=True, autoincrement=True)

    pricing_type = Column(String(30), nullable=False)
    resource_type = Column(String(50), nullable=True)
    flow_category = Column(String(50), nullable=True)

    base_cost = Column(Numeric(10, 4), nullable=False)
    unit = Column(String(20), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)
    effective_from = Column(DateTime(timezone=True), server_default=func.now())
    effective_until = Column(DateTime(timezone=True), nullable=True)
    priority = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("pricing_type IN ('task_type', 'resource', 'sandbox', 'bonus')"),
        CheckConstraint("unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', 'per_session', 'per_user')"),
    )


class CookieConsumptionLog(Base):
    __tablename__ = "cookie_consumption_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    task_id = Column(String(100), nullable=True)
    sandbox_session_id = Column(String(100), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    transaction_id = Column(BigInteger, ForeignKey("cookie_transactions.id"), nullable=True)

    billing_item = Column(String(50), nullable=False)
    quantity = Column(Numeric(10, 4), nullable=False)
    unit_price = Column(Numeric(10, 4), nullable=False)
    total_cost = Column(Numeric(10, 2), nullable=False)

    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "billing_item IN ('task_base', 'cpu_usage', 'memory_usage', "
            "'execution_time', 'sandbox_session', 'sandbox_cpu', 'sandbox_memory')"
        ),
    )


class CookieLedger(Base):
    __tablename__ = "cookie_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    snapshot_date = Column(Date, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("cookie_accounts.id"), nullable=False)

    opening_balance = Column(Numeric(12, 2), nullable=False)
    total_earned = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_spent = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_adjusted = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    closing_balance = Column(Numeric(12, 2), nullable=False)
    transaction_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("snapshot_date", "user_id"),
    )
```

### 8.3 Router 注册

```python
"""
在 app/api/v1/router.py 中注册路由:
"""
from fastapi import APIRouter

from app.api.v1.endpoints import cookies, admin_cookies

api_router = APIRouter()

# 用户端
cookie_router = APIRouter(prefix="/api/v1", tags=["cookies"])
cookie_router.include_router(cookies.router)

# 管理员端
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin-cookies"])
admin_router.include_router(admin_cookies.router)

api_router.include_router(cookie_router)
api_router.include_router(admin_router)
```

### 8.4 Celery Beat 配置

```python
"""
在 app/celery_app.py 中配置定时任务:
"""
from celery import Celery
from celery.schedules import crontab

app = Celery("cygnus_x")

app.conf.beat_schedule = {
    # 沙盒计费心跳：每分钟执行一次
    "sandbox-billing-tick": {
        "task": "app.services.sandbox_cookie_consumer.sandbox_billing_tick",
        "schedule": 60.0,  # 60秒
        "options": {"expires": 30},
    },
    # 日终账本快照：每天 00:05
    "daily-ledger-snapshot": {
        "task": "app.services.cookie_service.create_daily_ledger",
        "schedule": crontab(hour=0, minute=5),
    },
    # 清理过期定价缓存：每5分钟
    "clear-pricing-cache": {
        "task": "app.services.pricing_engine.clear_cache",
        "schedule": 300.0,
    },
}

app.conf.timezone = "Asia/Shanghai"
```

---

## 9. 架构设计说明

### 9.1 并发安全设计

```
并发控制策略:

1. 悲观锁 (SELECT FOR UPDATE)
   - 在 CookieService.spend/earn/adjust 中
   - 锁定 cookie_accounts 单行记录
   - 确保同一用户的并发操作串行化

2. 事务隔离
   - 所有资金操作在同一个数据库事务中
   - 扣减余额 + 记录流水原子执行
   - 事务提交后才释放锁

3. 预扣模式
   - 任务提交时预扣: balance -= amount, frozen_balance += amount
   - 任务完成后结算: unfreeze(退还预扣) + spend(扣除实际)
   - 避免任务执行期间余额被其他消费占用

4. 数据库约束
   - CHECK 约束确保金额符号正确
   - UNIQUE(user_id) 防止重复账户
   - NOT NULL 约束防止空值

防超支保证:
  由于使用行级锁 + 同一事务内检查余额并扣减，
  并发场景下不可能出现超支（余额不会变为负数）。
```

### 9.2 审计链设计

```
不可篡改审计链:

1. cookie_transactions 表只增不改不删
2. 每条记录包含 balance_after（交易后余额快照）
3. 通过触发器自动更新账户统计字段
4. 管理员操作记录 admin_id 和 adjust_reason
5. IP地址和操作时间完整记录
6. 消费明细 cookie_consumption_logs 提供细粒度对账

余额校验公式:
  当前余额 = SUM(txn.amount WHERE txn.txn_type IN ('earn', 'adjust'))
          - SUM(ABS(txn.amount) WHERE txn.txn_type IN ('spend', 'freeze'))
          + SUM(txn.amount WHERE txn.txn_type IN ('refund', 'unfreeze'))

  应等于: cookie_accounts.balance

对账接口: 管理员可定期运行校验脚本验证余额一致性
```

### 9.3 系统交互时序图

```
任务提交扣费时序:

  用户          FastAPI           CookieService       PricingEngine      PostgreSQL        Celery
   |               |                   |                   |                  |              |
   | POST /tasks   |                   |                   |                  |              |
   |-------------->|                   |                   |                  |              |
   |               | check_balance()   |                   |                  |              |
   |               |------------------>|                   |                  |              |
   |               |                   | SELECT FOR UPDATE |                  |              |
   |               |                   |------------------------------------->|              |
   |               |                   | balance >= required?                 |              |
   |               |                   |<--------------------------------------|              |
   |               | OK                |                   |                  |              |
   |               |<------------------|                   |                  |              |
   |               | prefreeze()       |                   |                  |              |
   |               |------------------>|                   |                  |              |
   |               |                   | INSERT txn(freeze)|                  |              |
   |               |                   | UPDATE balance    |                  |              |
   |               |                   |------------------------------------->|              |
   |               |                   | COMMIT            |                  |              |
   |               |                   |<--------------------------------------|              |
   |  402/200      |                   |                   |                  |              |
   |<--------------|                   |                   |                  |              |
   |               |                   |                   |                  |              |
   |               |                                    [Celery 任务执行中...]              |
   |               |                   |                   |                  |              |
   |               |<=========================================== 任务完成回调 =============|
   |               | settle()          |                   |                  |              |
   |               |------------------>|                   |                  |              |
   |               |                   | unfreeze + spend  |                  |              |
   |               |                   |------------------------------------->|              |
   |               |                   | COMMIT            |                  |              |
   |               |                   |<--------------------------------------|              |
   |   200 OK      |                   |                   |                  |              |
   |<--------------|                   |                   |                  |              |
```

### 9.4 扩展性考虑

```
未来扩展点:

1. 多币种支持:
   - cookie_pricing 增加 currency 字段
   - 支持不同币种汇率转换

2. 优惠券系统:
   - 新增 cookie_coupons 表
   - 交易时应用优惠码

3. 套餐/会员制:
   - 新增 cookie_plans 表
   - 用户订阅套餐获得折扣

4. 饼干市场:
   - 用户间转让饼干
   - 增加 transfer 类型的交易

5. 自动充值:
   - 余额低于阈值时自动通知
   - 集成支付系统

6. 分级定价:
   - 根据用户使用量提供阶梯价格
   - cookie_pricing 增加 tier 字段
```

---

## 10. 文件清单

| 文件 | 说明 |
|------|------|
| `alembic/versions/20250101_add_cookie_system.py` | Alembic 迁移脚本 |
| `app/models/cookie.py` | SQLAlchemy ORM 模型 (5个表) |
| `app/schemas/cookie.py` | Pydantic v2 DTO 定义 |
| `app/services/cookie_service.py` | CookieService 核心业务 |
| `app/services/pricing_engine.py` | PricingEngine 定价计算 |
| `app/services/task_cookie_consumer.py` | 任务饼干消费者 |
| `app/services/sandbox_cookie_consumer.py` | 沙盒饼干消费者 |
| `app/middleware/cookie_middleware.py` | 消费拦截中间件 |
| `app/api/v1/endpoints/cookies.py` | 用户端 API 路由 |
| `app/api/v1/endpoints/admin_cookies.py` | 管理员端 API 路由 |
| `app/exceptions.py` | 自定义异常类 |
| `app/celery_app.py` | Celery 定时任务配置 |

---

*文档结束 — CygnusX 饼干积分系统完整后端架构设计 v1.0*
