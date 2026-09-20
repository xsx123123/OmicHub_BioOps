# CygnusX 🥫 饼干积分系统设计文档

> **文档版本**：v1.0  
> **项目**：CygnusX — 私有化多组学分析平台  
> **模块**：饼干积分系统（Cookie System）  
> **日期**：2025-06-24  
> **目标读者**：系统架构师、全栈开发工程师、生信维护人员  

---

## 文档概要

本文档详细描述了 CygnusX 平台的 **🥫 饼干积分系统** 的完整设计方案，包括：

| 章节 | 内容 |
|------|------|
| 12.1 后端架构设计 | 数据库Schema（5张表）、Pydantic DTO、CookieService业务逻辑、定价引擎、消费拦截器 |
| 12.2 前端界面设计 | Header余额显示、用户账户页面、管理后台、任务提交预估、Pinia Store |
| 12.3 与主框架融合 | 8个系统集成点、数据库迁移脚本、部署配置、AI Agent集成、向后兼容性 |

### 核心功能

- **普通用户**：提交任务/运行沙盒消耗饼干，可查看余额和交易明细
- **管理员**：充值、扣减、冻结账户、配置定价策略、查看统计仪表盘
- **系统集成**：与任务系统、沙盒系统、AI Agent深度集成，预扣+结算模式防超支

---



---

# 12.1 饼干系统 — 后端架构设计

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


---



---

# 12.2 饼干系统 — 前端界面设计

# CygnusX 🥫 饼干积分系统 — 前端完整设计文档

> 技术栈：Vue 3 + TypeScript + Vite + Naive UI + Pinia + ECharts  
> 版本：v1.0  |  作者：CygnusX Frontend Team

---

## 目录

1. [TypeScript 类型定义](#1-typescript-类型定义)
2. [Pinia Store — cookie.ts](#2-pinia-store)
3. [WebSocket Composable — useCookieWebSocket](#3-websocket-composable)
4. [全局组件 — CookieBalanceBadge.vue](#4-cookiebalancebadgevue)
5. [用户页面 — CookieAccountView.vue](#5-cookieaccountviewvue)
6. [管理后台 — AdminCookieManagementView.vue](#6-admincookiemanagementviewvue)
7. [管理弹窗 — CookieAdjustModal.vue](#7-cookieadjustmodalvue)
8. [交易流水 — AdminCookieTransactionsView.vue](#8-admincookietransactionsviewvue)
9. [定价策略 — AdminCookiePricingView.vue](#9-admincookiepricingviewvue)
10. [任务提交 — TaskSubmitView.vue 饼干预估更新](#10-tasksubmitvue-饼干预估更新)
11. [路由配置](#11-路由配置)
12. [API 接口清单](#12-api-接口清单)

---

## 1. TypeScript 类型定义

```typescript
// types/cookie.d.ts

/** 交易类型 */
export type TransactionType = 'earn' | 'spend' | 'adjust' | 'refund' | 'recharge'

/** 账户状态 */
export type AccountStatus = 'active' | 'frozen' | 'suspended'

/** 定价生效状态 */
export type PricingStatus = 'active' | 'inactive'

/** 资源类型 */
export type ResourceType = 'cpu' | 'memory' | 'gpu'

/** 任务流程类别 */
export type FlowCategory =
  | 'rna_seq'
  | 'chip_seq'
  | 'atac_seq'
  | 'wgs'
  | 'proteomics'
  | 'metabolomics'
  | 'sc_rna_seq'
  | 'data_integration'

// ─────────────────────────────────────────────
// 账户相关
// ─────────────────────────────────────────────

export interface CookieAccount {
  userId: number
  userName: string
  email: string
  avatar?: string
  balance: number
  totalEarned: number
  totalSpent: number
  status: AccountStatus
  lastActiveAt: string
  createdAt: string
  updatedAt: string
}

export interface CookieAccountSummary {
  currentBalance: number
  monthlySpent: number
  monthlyEarned: number
  groupRank: number       // 组内消费排名
  totalGroupMembers: number
}

// ─────────────────────────────────────────────
// 交易流水
// ─────────────────────────────────────────────

export interface CookieTransaction {
  id: number
  userId: number
  userName: string
  type: TransactionType
  amount: number          // 正数 = 收入，负数 = 支出
  balanceAfter: number    // 变动后余额
  description: string
  relatedTaskId?: number  // 关联任务ID
  relatedFlowCategory?: FlowCategory
  operatorId?: number     // 操作者ID（管理员操作）
  operatorName?: string
  createdAt: string
}

export interface TransactionFilters {
  type?: TransactionType | 'all'
  startDate?: string
  endDate?: string
  minAmount?: number
  maxAmount?: number
  page?: number
  pageSize?: number
}

// ─────────────────────────────────────────────
// 费用预估
// ─────────────────────────────────────────────

export interface ResourceEstimate {
  resourceType: ResourceType
  quantity: number        // CPU核数 / 内存GB / GPU卡数
  duration: number        // 小时
  unitPrice: number       // 每小时单价
  subtotal: number
}

export interface CostEstimate {
  flowCategory: FlowCategory
  baseFee: number
  resources: ResourceEstimate[]
  total: number
  discountRate: number    // 折扣率（如0.9 = 9折）
  discountedTotal: number
  currencyUnit: string    // "cookie"
}

export interface EstimateParams {
  flowCategory: FlowCategory
  cpuCores: number
  memoryGb: number
  gpuCards?: number
  estimatedHours: number
}

// ─────────────────────────────────────────────
// 管理员相关
// ─────────────────────────────────────────────

export interface AdminAccountFilters {
  search?: string         // 用户名/邮箱搜索
  status?: AccountStatus | 'all'
  sortBy?: 'balance' | 'totalSpent' | 'lastActiveAt'
  sortOrder?: 'asc' | 'desc'
  page?: number
  pageSize?: number
}

export interface CookieAdjustParams {
  userId: number
  amount: number          // 正数充值 / 负数扣减
  reason: string
  password: string        // 管理员二次确认密码
}

// ─────────────────────────────────────────────
// 定价策略
// ─────────────────────────────────────────────

export interface CookiePricing {
  id: number
  flowCategory: FlowCategory
  resourceType: ResourceType
  unitPrice: number       // 每小时单价（饼干）
  description: string
  status: PricingStatus
  effectiveFrom: string
  effectiveTo?: string
  createdAt: string
  updatedAt: string
}

export interface PricingFormData {
  flowCategory: FlowCategory
  resourceType: ResourceType
  unitPrice: number
  description: string
  effectiveFrom: string
  effectiveTo?: string
}

// ─────────────────────────────────────────────
// WebSocket 事件
// ─────────────────────────────────────────────

export interface BalanceUpdatedEvent {
  type: 'cookie.balance_updated'
  payload: {
    newBalance: number
    change: number
    reason: string
    timestamp: string
  }
}

export interface SystemStatsEvent {
  type: 'cookie.system_stats'
  payload: {
    totalCirculation: number
    todayConsumption: number
    activeAccounts: number
    pendingRecharges: number
  }
}

export type CookieWebSocketEvent = BalanceUpdatedEvent | SystemStatsEvent

// ─────────────────────────────────────────────
// 图表数据
// ─────────────────────────────────────────────

export interface DailyTrend {
  date: string
  spent: number
  earned: number
}

export interface CategoryBreakdown {
  category: FlowCategory
  label: string
  amount: number
  percentage: number
}

export interface AccountStats {
  dailyTrend: DailyTrend[]
  categoryBreakdown: CategoryBreakdown[]
}

// ─────────────────────────────────────────────
// 系统统计（管理员）
// ─────────────────────────────────────────────

export interface SystemStatistics {
  totalCirculation: number    // 系统总流通饼干
  todayConsumption: number
  todayRecharge: number
  activeAccounts: number
  frozenAccounts: number
  pendingRecharges: number
  monthlyGrowth: number       // 月增长率
}
```

---

## 2. Pinia Store

```typescript
// stores/modules/cookie.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  CookieAccount,
  CookieAccountSummary,
  CookieTransaction,
  TransactionFilters,
  CookiePricing,
  CostEstimate,
  EstimateParams,
  AdminAccountFilters,
  CookieAdjustParams,
  AccountStats,
  SystemStatistics,
  BalanceUpdatedEvent,
  CookieWebSocketEvent,
} from '@/types/cookie'
import { useWebSocket } from '@/composables/useWebSocket'

export const useCookieStore = defineStore('cookie', () => {
  // ═══════════════════════════════════════════
  // State
  // ═══════════════════════════════════════════

  const account = ref<CookieAccount | null>(null)
  const accountSummary = ref<CookieAccountSummary | null>(null)
  const transactions = ref<CookieTransaction[]>([])
  const transactionTotal = ref(0)
  const pricing = ref<CookiePricing[]>([])
  const estimate = ref<CostEstimate | null>(null)
  const accountStats = ref<AccountStats | null>(null)
  const systemStats = ref<SystemStatistics | null>(null)
  const adminAccounts = ref<CookieAccount[]>([])
  const adminAccountTotal = ref(0)
  const isLoading = ref(false)
  const wsConnected = ref(false)

  // 最近3笔交易（用于 Header 悬浮卡片）
  const recentTransactions = computed(() => transactions.value.slice(0, 3))

  // 格式化余额
  const formattedBalance = computed(() => {
    if (!account.value) return '0'
    return account.value.balance.toLocaleString()
  })

  // 余额是否充足
  const hasEnoughBalance = computed(() => {
    if (!account.value || !estimate.value) return false
    return account.value.balance >= estimate.value.discountedTotal
  })

  // ═══════════════════════════════════════════
  // Actions — 个人账户
  // ═══════════════════════════════════════════

  /** 获取当前用户账户信息 */
  async function fetchAccount() {
    isLoading.value = true
    try {
      const res = await fetch('/api/v1/cookies/account')
      const data = await res.json()
      account.value = data.data
    } catch (err) {
      console.error('获取饼干账户失败:', err)
      throw err
    } finally {
      isLoading.value = false
    }
  }

  /** 获取账户统计摘要 */
  async function fetchAccountSummary() {
    try {
      const res = await fetch('/api/v1/cookies/account/summary')
      const data = await res.json()
      accountSummary.value = data.data
    } catch (err) {
      console.error('获取账户摘要失败:', err)
    }
  }

  /** 获取交易流水 */
  async function fetchTransactions(filters: TransactionFilters = {}) {
    isLoading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.type && filters.type !== 'all') params.append('type', filters.type)
      if (filters.startDate) params.append('startDate', filters.startDate)
      if (filters.endDate) params.append('endDate', filters.endDate)
      if (filters.minAmount !== undefined) params.append('minAmount', String(filters.minAmount))
      if (filters.maxAmount !== undefined) params.append('maxAmount', String(filters.maxAmount))
      params.append('page', String(filters.page ?? 1))
      params.append('pageSize', String(filters.pageSize ?? 20))

      const res = await fetch(`/api/v1/cookies/transactions?${params}`)
      const data = await res.json()
      transactions.value = data.data.list
      transactionTotal.value = data.data.total
    } catch (err) {
      console.error('获取交易流水失败:', err)
    } finally {
      isLoading.value = false
    }
  }

  /** 获取图表统计数据 */
  async function fetchAccountStats() {
    try {
      const res = await fetch('/api/v1/cookies/account/stats')
      const data = await res.json()
      accountStats.value = data.data
    } catch (err) {
      console.error('获取账户统计失败:', err)
    }
  }

  // ═══════════════════════════════════════════
  // Actions — 费用预估
  // ═══════════════════════════════════════════

  /** 预估任务费用 */
  async function estimateTaskCost(params: EstimateParams) {
    try {
      const res = await fetch('/api/v1/cookies/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
      const data = await res.json()
      estimate.value = data.data
      return data.data
    } catch (err) {
      console.error('费用预估失败:', err)
      estimate.value = null
      throw err
    }
  }

  /** 清除预估 */
  function clearEstimate() {
    estimate.value = null
  }

  // ═══════════════════════════════════════════
  // Actions — 管理员功能
  // ═══════════════════════════════════════════

  /** 获取系统统计（管理员） */
  async function fetchSystemStats() {
    try {
      const res = await fetch('/api/v1/admin/cookies/statistics')
      const data = await res.json()
      systemStats.value = data.data
    } catch (err) {
      console.error('获取系统统计失败:', err)
    }
  }

  /** 获取用户账户列表（管理员） */
  async function fetchAdminAccounts(filters: AdminAccountFilters = {}) {
    isLoading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.search) params.append('search', filters.search)
      if (filters.status && filters.status !== 'all') params.append('status', filters.status)
      if (filters.sortBy) params.append('sortBy', filters.sortBy)
      if (filters.sortOrder) params.append('sortOrder', filters.sortOrder)
      params.append('page', String(filters.page ?? 1))
      params.append('pageSize', String(filters.pageSize ?? 20))

      const res = await fetch(`/api/v1/admin/cookies/accounts?${params}`)
      const data = await res.json()
      adminAccounts.value = data.data.list
      adminAccountTotal.value = data.data.total
    } catch (err) {
      console.error('获取用户账户列表失败:', err)
    } finally {
      isLoading.value = false
    }
  }

  /** 调整用户余额（充值/扣减） */
  async function adjustBalance(params: CookieAdjustParams) {
    const res = await fetch(`/api/v1/admin/cookies/accounts/${params.userId}/adjust`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: params.amount,
        reason: params.reason,
        password: params.password,
      }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '调整余额失败')
    }
    const data = await res.json()
    // 刷新列表
    await fetchAdminAccounts()
    return data.data
  }

  /** 冻结/解冻账户 */
  async function toggleAccountStatus(userId: number, status: 'active' | 'frozen') {
    const res = await fetch(`/api/v1/admin/cookies/accounts/${userId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '操作失败')
    }
    // 更新本地状态
    const idx = adminAccounts.value.findIndex(a => a.userId === userId)
    if (idx !== -1) {
      adminAccounts.value[idx].status = status
    }
    return await res.json()
  }

  // ═══════════════════════════════════════════
  // Actions — 定价策略
  // ═══════════════════════════════════════════

  /** 获取定价策略列表 */
  async function fetchPricing() {
    try {
      const res = await fetch('/api/v1/admin/cookies/pricing')
      const data = await res.json()
      pricing.value = data.data
    } catch (err) {
      console.error('获取定价策略失败:', err)
    }
  }

  /** 创建定价策略 */
  async function createPricing(data: PricingFormData) {
    const res = await fetch('/api/v1/admin/cookies/pricing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '创建失败')
    }
    await fetchPricing()
    return await res.json()
  }

  /** 更新定价策略 */
  async function updatePricing(id: number, data: Partial<PricingFormData>) {
    const res = await fetch(`/api/v1/admin/cookies/pricing/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '更新失败')
    }
    await fetchPricing()
    return await res.json()
  }

  /** 切换定价状态 */
  async function togglePricingStatus(id: number, status: PricingStatus) {
    return updatePricing(id, { status })
  }

  // ═══════════════════════════════════════════
  // Actions — WebSocket
  // ═══════════════════════════════════════════

  let wsCleanup: (() => void) | null = null

  /** 订阅余额变动推送 */
  function subscribeBalanceUpdates() {
    const { connect, disconnect, onMessage } = useWebSocket()

    connect('/ws/cookies')
    wsConnected.value = true

    const unsubscribe = onMessage((event: CookieWebSocketEvent) => {
      if (event.type === 'cookie.balance_updated') {
        handleBalanceUpdate(event.payload)
      } else if (event.type === 'cookie.system_stats') {
        systemStats.value = event.payload
      }
    })

    wsCleanup = () => {
      unsubscribe()
      disconnect()
      wsConnected.value = false
    }
  }

  /** 处理余额更新事件 */
  function handleBalanceUpdate(payload: BalanceUpdatedEvent['payload']) {
    if (account.value) {
      account.value.balance = payload.newBalance
      // 如果 change > 0 则增加 totalEarned，否则增加 totalSpent
      if (payload.change > 0) {
        account.value.totalEarned += payload.change
      } else {
        account.value.totalSpent += Math.abs(payload.change)
      }
    }
    // 触发 UI 动画效果
    if (typeof document !== 'undefined') {
      document.dispatchEvent(new CustomEvent('cookie-balance-bump', {
        detail: payload,
      }))
    }
  }

  /** 取消订阅 */
  function unsubscribeBalanceUpdates() {
    wsCleanup?.()
    wsCleanup = null
  }

  // ═══════════════════════════════════════════
  // Return
  // ═══════════════════════════════════════════

  return {
    // State
    account,
    accountSummary,
    transactions,
    transactionTotal,
    pricing,
    estimate,
    accountStats,
    systemStats,
    adminAccounts,
    adminAccountTotal,
    isLoading,
    wsConnected,

    // Computed
    recentTransactions,
    formattedBalance,
    hasEnoughBalance,

    // Actions
    fetchAccount,
    fetchAccountSummary,
    fetchTransactions,
    fetchAccountStats,
    estimateTaskCost,
    clearEstimate,
    fetchSystemStats,
    fetchAdminAccounts,
    adjustBalance,
    toggleAccountStatus,
    fetchPricing,
    createPricing,
    updatePricing,
    togglePricingStatus,
    subscribeBalanceUpdates,
    unsubscribeBalanceUpdates,
  }
})
```

---

## 3. WebSocket Composable

```typescript
// composables/useWebSocket.ts
import { ref, onUnmounted } from 'vue'

export function useWebSocket() {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  const messageHandlers = ref<((event: any) => void)[]>([])

  function connect(url: string) {
    // 支持自动协议切换和 token 注入
    const token = localStorage.getItem('access_token')
    const fullUrl = `${url}?token=${token}`

    ws.value = new WebSocket(fullUrl)

    ws.value.onopen = () => {
      isConnected.value = true
      console.log('[WebSocket] 已连接:', url)
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        messageHandlers.value.forEach(handler => handler(data))
      } catch (err) {
        console.error('[WebSocket] 消息解析失败:', err)
      }
    }

    ws.value.onclose = () => {
      isConnected.value = false
      console.log('[WebSocket] 连接已关闭')
    }

    ws.value.onerror = (err) => {
      console.error('[WebSocket] 错误:', err)
      isConnected.value = false
    }

    // 页面关闭时自动断开
    onUnmounted(() => {
      disconnect()
    })
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
      isConnected.value = false
    }
  }

  function onMessage(handler: (event: any) => void) {
    messageHandlers.value.push(handler)
    // 返回取消订阅函数
    return () => {
      const idx = messageHandlers.value.indexOf(handler)
      if (idx !== -1) messageHandlers.value.splice(idx, 1)
    }
  }

  function send(data: any) {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 连接未就绪，无法发送消息')
    }
  }

  return {
    ws,
    isConnected,
    connect,
    disconnect,
    onMessage,
    send,
  }
}
```

---

## 4. CookieBalanceBadge.vue

```vue
<!-- components/cookie/CookieBalanceBadge.vue -->
<template>
  <n-popover trigger="hover" :delay="200" :duration="300" :show-arrow="false">
    <template #trigger>
      <n-button text class="cookie-balance-btn" @click="handleClick">
        <n-badge
          :value="badgeValue"
          :max="99999"
          :type="badgeType"
          :show-zero="false"
          :offset="[-4, 4]"
        >
          <n-icon
            size="20"
            class="cookie-icon"
            :class="{ 'bump-animation': isBumping }"
          >
            <CookieOutline />
          </n-icon>
        </n-badge>
        <n-text :depth="1" class="balance-text">
          {{ formattedBalance }}
        </n-text>
      </n-button>
    </template>

    <!-- 悬浮卡片内容 -->
    <div class="cookie-popover-card">
      <!-- 余额展示 -->
      <div class="balance-section">
        <n-statistic label="我的饼干余额" tabular-nums>
          <template #prefix>
            <n-icon size="24" color="#f5a623">
              <CookieOutline />
            </n-icon>
          </template>
          <n-number-animation
            :from="prevBalance"
            :to="currentBalance"
            :duration="800"
          />
          <template #suffix>🥫</template>
        </n-statistic>
      </div>

      <n-divider style="margin: 8px 0" />

      <!-- 最近3笔交易 -->
      <div class="recent-transactions">
        <n-text depth="3" style="font-size: 12px;">近期变动</n-text>
        <n-empty
          v-if="!recentTransactions.length"
          description="暂无记录"
          size="small"
        />
        <n-space v-else vertical :size="4" style="margin-top: 6px;">
          <n-space
            v-for="tx in recentTransactions"
            :key="tx.id"
            justify="space-between"
            align="center"
            class="tx-item"
          >
            <n-space align="center" :size="6">
              <n-tag
                :type="getTxTypeColor(tx.type)"
                size="tiny"
                round
              >
                {{ getTxTypeLabel(tx.type) }}
              </n-tag>
              <n-ellipsis style="max-width: 120px; font-size: 12px;">
                {{ tx.description }}
              </n-ellipsis>
            </n-space>
            <n-text
              :type="tx.amount > 0 ? 'success' : 'error'"
              strong
              style="font-size: 13px;"
            >
              {{ tx.amount > 0 ? '+' : '' }}{{ tx.amount }}
            </n-text>
          </n-space>
        </n-space>
      </div>

      <n-divider style="margin: 8px 0" />

      <!-- 快捷入口 -->
      <n-space justify="space-between" align="center">
        <n-text depth="3" style="font-size: 12px;">
          账户状态：
          <n-tag
            :type="account?.status === 'active' ? 'success' : 'error'"
            size="tiny"
            round
          >
            {{ account?.status === 'active' ? '正常' : '已冻结' }}
          </n-tag>
        </n-text>
        <n-button
          text
          type="primary"
          size="tiny"
          @click="handleClick"
        >
          查看明细 →
        </n-button>
      </n-space>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPopover, NBadge, NButton, NIcon, NText, NStatistic,
  NNumberAnimation, NDivider, NSpace, NTag, NEmpty, NEllipsis,
} from 'naive-ui'
import { CookieOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── Local State ────────────────────────────
const isBumping = ref(false)
const prevBalance = ref(0)
const currentBalance = computed(() => account.value?.balance ?? 0)
const bumpTimer = ref<ReturnType<typeof setTimeout> | null>(null)

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const formattedBalance = computed(() => cookieStore.formattedBalance)
const recentTransactions = computed<CookieTransaction[]>(() => cookieStore.recentTransactions)

const badgeValue = computed(() => {
  // 仅在有变动时显示红点提示
  return 0 // 动态红点逻辑可由外部控制
})

const badgeType = computed(() => 'warning' as const)

// ── Watchers ───────────────────────────────

// 监听余额变化 → 触发弹跳动画
watch(() => account.value?.balance, (newVal, oldVal) => {
  if (newVal !== undefined && oldVal !== undefined && newVal !== oldVal) {
    prevBalance.value = oldVal
    triggerBumpAnimation()
  }
}, { immediate: false })

// 监听全局余额变动事件
function handleBalanceBumpEvent(e: Event) {
  triggerBumpAnimation()
}

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  // 订阅 WebSocket 余额推送
  cookieStore.subscribeBalanceUpdates()
  // 获取账户信息
  cookieStore.fetchAccount()
  cookieStore.fetchTransactions({ pageSize: 3 })
  // 监听全局动画事件
  document.addEventListener('cookie-balance-bump', handleBalanceBumpEvent)
})

onUnmounted(() => {
  cookieStore.unsubscribeBalanceUpdates()
  document.removeEventListener('cookie-balance-bump', handleBalanceBumpEvent)
  if (bumpTimer.value) clearTimeout(bumpTimer.value)
})

// ── Methods ────────────────────────────────

function triggerBumpAnimation() {
  isBumping.value = true
  if (bumpTimer.value) clearTimeout(bumpTimer.value)
  bumpTimer.value = setTimeout(() => {
    isBumping.value = false
  }, 600)
}

function handleClick() {
  router.push('/cookies/account')
}

function getTxTypeColor(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxTypeLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得',
    spend: '消费',
    adjust: '调整',
    refund: '退款',
    recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.cookie-balance-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.2s;
}

.cookie-balance-btn:hover {
  background-color: var(--n-button-color-hover);
}

.cookie-icon {
  color: #f5a623;
  transition: transform 0.3s ease;
}

.balance-text {
  font-weight: 600;
  font-size: 14px;
  color: #f5a623;
}

/* 弹跳动画 */
@keyframes cookie-bump {
  0%   { transform: scale(1) rotate(0deg); }
  25%  { transform: scale(1.25) rotate(-10deg); }
  50%  { transform: scale(1.1) rotate(5deg); }
  75%  { transform: scale(1.2) rotate(-5deg); }
  100% { transform: scale(1) rotate(0deg); }
}

.bump-animation {
  animation: cookie-bump 0.6s ease-in-out;
}

/* 悬浮卡片样式 */
.cookie-popover-card {
  min-width: 260px;
  padding: 4px;
}

.balance-section {
  text-align: center;
  padding: 8px 0;
}

.recent-transactions {
  max-height: 180px;
  overflow-y: auto;
}

.tx-item {
  padding: 4px 6px;
  border-radius: 6px;
  transition: background-color 0.15s;
}

.tx-item:hover {
  background-color: var(--n-action-color);
}

/* 暗色模式适配 */
:deep(.n-statistic-value) {
  color: var(--n-text-color);
}

:deep(.n-statistic-value__suffix) {
  font-size: 18px;
}
</style>
```

---

## 5. CookieAccountView.vue

```vue
<!-- views/cookie/CookieAccountView.vue -->
<template>
  <div class="cookie-account-page">
    <!-- 页面标题 -->
    <n-page-header title="🥫 我的饼干账户" subtitle="查看饼干余额、交易流水与消费统计" />

    <n-space vertical :size="24" style="margin-top: 20px;">

      <!-- ═══════════ 顶部统计卡片行 ═══════════ -->
      <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
        <!-- 当前余额 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--primary" :bordered="false">
            <n-statistic label="当前余额" tabular-nums>
              <template #prefix>
                <n-icon size="28" color="#f5a623"><CookieOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--primary">
                {{ formattedBalance }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-tag
              :type="account?.status === 'active' ? 'success' : 'error'"
              size="small"
              round
              class="status-tag"
            >
              {{ account?.status === 'active' ? '账户正常' : '账户已冻结' }}
            </n-tag>
          </n-card>
        </n-grid-item>

        <!-- 本月消费 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--danger" :bordered="false">
            <n-statistic label="本月消费" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#d03050"><TrendingDownOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--danger">
                {{ summary?.monthlySpent ?? 0 }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">较上月 --</n-text>
          </n-card>
        </n-grid-item>

        <!-- 本月获得 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--success" :bordered="false">
            <n-statistic label="本月获得" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#18a058"><TrendingUpOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--success">
                {{ summary?.monthlyEarned ?? 0 }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">含系统奖励</n-text>
          </n-card>
        </n-grid-item>

        <!-- 组内排名 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--info" :bordered="false">
            <n-statistic label="消费排名" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#2080f0"><TrophyOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--info">
                {{ summary?.groupRank ?? '--' }}
              </span>
              <template #suffix>/ {{ summary?.totalGroupMembers ?? '--' }}</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">组内排名</n-text>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 中部图表区 ═══════════ -->
      <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen">
        <!-- 消费趋势折线图 -->
        <n-grid-item span="2 m:1">
          <n-card title="📈 消费趋势（近30天）" :bordered="false">
            <div ref="trendChartRef" class="chart-container" />
          </n-card>
        </n-grid-item>

        <!-- 消费类型饼图 -->
        <n-grid-item span="2 m:1">
          <n-card title="📊 消费构成" :bordered="false">
            <div ref="pieChartRef" class="chart-container" />
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 底部交易流水表格 ═══════════ -->
      <n-card title="🧾 交易流水" :bordered="false">
        <!-- 筛选条件 -->
        <n-space align="center" wrap :size="12" style="margin-bottom: 16px;">
          <n-select
            v-model:value="filters.type"
            :options="typeOptions"
            placeholder="交易类型"
            clearable
            style="width: 140px;"
          />
          <n-date-picker
            v-model:formatted-value="filters.startDate"
            type="date"
            placeholder="开始日期"
            value-format="yyyy-MM-dd"
          />
          <n-date-picker
            v-model:formatted-value="filters.endDate"
            type="date"
            placeholder="结束日期"
            value-format="yyyy-MM-dd"
          />
          <n-input-number
            v-model:value="filters.minAmount"
            placeholder="最小金额"
            :min="0"
            style="width: 130px;"
          />
          <n-input-number
            v-model:value="filters.maxAmount"
            placeholder="最大金额"
            :min="0"
            style="width: 130px;"
          />
          <n-button type="primary" @click="handleSearch">
            <template #icon><n-icon><SearchOutline /></n-icon></template>
            查询
          </n-button>
          <n-button @click="handleReset">重置</n-button>
        </n-space>

        <!-- 表格 -->
        <n-data-table
          :columns="columns"
          :data="transactions"
          :loading="isLoading"
          :pagination="pagination"
          :row-key="(row: CookieTransaction) => row.id"
          @update:page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NGrid, NGridItem, NCard, NStatistic, NIcon,
  NText, NTag, NSpace, NSelect, NDatePicker, NInputNumber,
  NButton, NDataTable, NDivider, NEllipsis, NEmpty,
} from 'naive-ui'
import {
  CookieOutline, TrendingDownOutline, TrendingUpOutline,
  TrophyOutline, SearchOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType, TransactionFilters } from '@/types/cookie'
import * as echarts from 'echarts'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const router = useRouter()
const cookieStore = useCookieStore()

// ── Refs ───────────────────────────────────
const trendChartRef = ref<HTMLDivElement>()
const pieChartRef = ref<HTMLDivElement>()
let trendChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null

// ── Filters ────────────────────────────────
const filters = ref<TransactionFilters>({
  type: 'all',
  startDate: undefined,
  endDate: undefined,
  minAmount: undefined,
  maxAmount: undefined,
  page: 1,
  pageSize: 20,
})

const typeOptions: SelectOption[] = [
  { label: '全部类型', value: 'all' },
  { label: '获得', value: 'earn' },
  { label: '消费', value: 'spend' },
  { label: '调整', value: 'adjust' },
  { label: '退款', value: 'refund' },
  { label: '充值', value: 'recharge' },
]

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const summary = computed(() => cookieStore.accountSummary)
const transactions = computed(() => cookieStore.transactions)
const transactionTotal = computed(() => cookieStore.transactionTotal)
const isLoading = computed(() => cookieStore.isLoading)
const formattedBalance = computed(() => cookieStore.formattedBalance)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 20,
  pageCount: Math.ceil(transactionTotal.value / (filters.value.pageSize ?? 20)),
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  showQuickJumper: true,
  prefix: () => `共 ${transactionTotal.value} 条`,
}))

// ── Table Columns ──────────────────────────
const columns = computed<DataTableColumns<CookieTransaction>>(() => [
  {
    title: '时间',
    key: 'createdAt',
    width: 170,
    render: (row) => formatDate(row.createdAt),
  },
  {
    title: '类型',
    key: 'type',
    width: 100,
    render: (row) => h(NTag, {
      type: getTxTagType(row.type),
      size: 'small',
      round: true,
    }, { default: () => getTxLabel(row.type) }),
  },
  {
    title: '金额',
    key: 'amount',
    width: 120,
    align: 'right',
    render: (row) => h('span', {
      style: {
        color: row.amount > 0 ? '#18a058' : '#d03050',
        fontWeight: 600,
      },
    }, `${row.amount > 0 ? '+' : ''}${row.amount} 🥫`),
  },
  {
    title: '余额',
    key: 'balanceAfter',
    width: 120,
    align: 'right',
    render: (row) => `${row.balanceAfter.toLocaleString()} 🥫`,
  },
  {
    title: '描述',
    key: 'description',
    render: (row) => h(NEllipsis, { style: 'max-width: 300px;' }, {
      default: () => row.description,
    }),
  },
  {
    title: '操作者',
    key: 'operatorName',
    width: 120,
    render: (row) => row.operatorName || '--',
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchAccount()
  cookieStore.fetchAccountSummary()
  cookieStore.fetchTransactions()
  cookieStore.fetchAccountStats()

  // 延迟初始化图表（确保 DOM 已渲染）
  setTimeout(() => {
    initTrendChart()
    initPieChart()
  }, 300)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  trendChart?.dispose()
  pieChart?.dispose()
  window.removeEventListener('resize', handleResize)
})

// ── Chart Methods ──────────────────────────

function initTrendChart() {
  if (!trendChartRef.value) return
  trendChart = echarts.init(trendChartRef.value, undefined, { renderer: 'svg' })

  const stats = cookieStore.accountStats
  const dates = stats?.dailyTrend.map(d => d.date) ?? []
  const spentData = stats?.dailyTrend.map(d => d.spent) ?? []
  const earnedData = stats?.dailyTrend.map(d => d.earned) ?? []

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'var(--n-card-color)',
      borderColor: 'var(--n-border-color)',
      textStyle: { color: 'var(--n-text-color)' },
    },
    legend: {
      data: ['消费', '获得'],
      textStyle: { color: 'var(--n-text-color)' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: 'var(--n-text-color-disabled)' } },
      axisLabel: { color: 'var(--n-text-color)' },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: 'var(--n-divider-color)' } },
      axisLabel: { color: 'var(--n-text-color)' },
    },
    series: [
      {
        name: '消费',
        type: 'line',
        smooth: true,
        data: spentData,
        itemStyle: { color: '#d03050' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(208, 48, 80, 0.3)' },
            { offset: 1, color: 'rgba(208, 48, 80, 0.02)' },
          ]),
        },
      },
      {
        name: '获得',
        type: 'line',
        smooth: true,
        data: earnedData,
        itemStyle: { color: '#18a058' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(24, 160, 88, 0.3)' },
            { offset: 1, color: 'rgba(24, 160, 88, 0.02)' },
          ]),
        },
      },
    ],
  }

  trendChart.setOption(option)
}

function initPieChart() {
  if (!pieChartRef.value) return
  pieChart = echarts.init(pieChartRef.value, undefined, { renderer: 'svg' })

  const stats = cookieStore.accountStats
  const data = stats?.categoryBreakdown.map(c => ({
    name: c.label,
    value: c.amount,
  })) ?? []

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 🥫 ({d}%)',
      backgroundColor: 'var(--n-card-color)',
      borderColor: 'var(--n-border-color)',
      textStyle: { color: 'var(--n-text-color)' },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { color: 'var(--n-text-color)' },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: 'var(--n-card-color)',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold',
            color: 'var(--n-text-color)',
          },
        },
        data,
      },
    ],
  }

  pieChart.setOption(option)
}

function handleResize() {
  trendChart?.resize()
  pieChart?.resize()
}

// ── Table Methods ──────────────────────────

function handleSearch() {
  filters.value.page = 1
  cookieStore.fetchTransactions(filters.value)
}

function handleReset() {
  filters.value = {
    type: 'all',
    startDate: undefined,
    endDate: undefined,
    minAmount: undefined,
    maxAmount: undefined,
    page: 1,
    pageSize: 20,
  }
  cookieStore.fetchTransactions(filters.value)
}

function handlePageChange(page: number) {
  filters.value.page = page
  cookieStore.fetchTransactions(filters.value)
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  cookieStore.fetchTransactions(filters.value)
}

// ── Helpers ────────────────────────────────

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getTxTagType(type: TransactionType) {
  const map: Record<string, 'success' | 'error' | 'info' | 'warning' | 'default'> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得',
    spend: '消费',
    adjust: '调整',
    refund: '退款',
    recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.cookie-account-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.stat-card {
  border-radius: 12px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--n-box-shadow);
}

.stat-card :deep(.n-card__content) {
  padding: 16px;
}

.stat-number {
  font-size: 28px;
  font-weight: 700;
}

.stat-number--primary { color: #f5a623; }
.stat-number--danger  { color: #d03050; }
.stat-number--success { color: #18a058; }
.stat-number--info    { color: #2080f0; }

.status-tag {
  margin-top: 8px;
}

.chart-container {
  width: 100%;
  height: 280px;
}

/* 暗色模式图表文字颜色适配 */
:deep(.n-statistic__label) {
  color: var(--n-text-color-3);
}
</style>
```

---

## 6. AdminCookieManagementView.vue

```vue
<!-- views/admin/AdminCookieManagementView.vue -->
<template>
  <div class="admin-cookie-page">
    <!-- 页面标题 -->
    <n-page-header title="🥫 饼干管理" subtitle="管理系统饼干流通、用户账户与充值" />

    <n-space vertical :size="20" style="margin-top: 20px;">

      <!-- ═══════════ 统计概览卡片 ═══════════ -->
      <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card" :bordered="false">
            <n-statistic label="系统总流通饼干">
              <template #prefix>
                <n-icon size="22" color="#f5a623"><ServerOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.totalCirculation ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--danger" :bordered="false">
            <n-statistic label="今日消费">
              <template #prefix>
                <n-icon size="22" color="#d03050"><TrendingDownOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.todayConsumption ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--success" :bordered="false">
            <n-statistic label="活跃账户数">
              <template #prefix>
                <n-icon size="22" color="#18a058"><PeopleOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.activeAccounts ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--warning" :bordered="false">
            <n-statistic label="待处理充值">
              <template #prefix>
                <n-icon size="22" color="#f0a020"><TimeOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.pendingRecharges ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 用户账户管理表格 ═══════════ -->
      <n-card title="👥 用户账户管理" :bordered="false">
        <!-- 搜索栏 -->
        <n-space align="center" wrap :size="12" style="margin-bottom: 16px;">
          <n-input
            v-model:value="filters.search"
            placeholder="搜索用户名或邮箱..."
            clearable
            style="width: 260px;"
          >
            <template #prefix>
              <n-icon><SearchOutline /></n-icon>
            </template>
          </n-input>
          <n-select
            v-model:value="filters.status"
            :options="statusOptions"
            placeholder="账户状态"
            clearable
            style="width: 140px;"
          />
          <n-select
            v-model:value="filters.sortBy"
            :options="sortOptions"
            placeholder="排序方式"
            style="width: 150px;"
          />
          <n-button type="primary" @click="handleSearch">
            <template #icon><n-icon><SearchOutline /></n-icon></template>
            查询
          </n-button>
          <n-button @click="handleReset">重置</n-button>
          <n-button @click="router.push('/admin/cookies/transactions')">
            <template #icon><n-icon><ListOutline /></n-icon></template>
            交易流水
          </n-button>
          <n-button @click="router.push('/admin/cookies/pricing')">
            <template #icon><n-icon><PricetagOutline /></n-icon></template>
            定价策略
          </n-button>
        </n-space>

        <!-- 用户账户表格 -->
        <n-data-table
          :columns="columns"
          :data="adminAccounts"
          :loading="isLoading"
          :pagination="pagination"
          :row-key="(row: CookieAccount) => row.userId"
          @update:page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        />
      </n-card>
    </n-space>

    <!-- ═══════════ 充值/扣减弹窗 ═══════════ -->
    <CookieAdjustModal
      v-model:show="showAdjustModal"
      :user="selectedUser"
      :mode="adjustMode"
      @success="handleAdjustSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NGrid, NGridItem, NCard, NStatistic, NIcon,
  NNumberAnimation, NSpace, NInput, NSelect, NButton,
  NDataTable, NTag, NPopconfirm, NText, NAvatar, NTooltip,
} from 'naive-ui'
import {
  ServerOutline, TrendingDownOutline, PeopleOutline,
  TimeOutline, SearchOutline, ListOutline, PricetagOutline,
  AddOutline, RemoveOutline, LockOpenOutline, LockClosedOutline,
  EyeOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import CookieAdjustModal from '@/components/cookie/CookieAdjustModal.vue'
import type { CookieAccount, AccountStatus, AdminAccountFilters } from '@/types/cookie'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const filters = ref<AdminAccountFilters>({
  search: '',
  status: 'all',
  sortBy: 'balance',
  sortOrder: 'desc',
  page: 1,
  pageSize: 20,
})
const showAdjustModal = ref(false)
const selectedUser = ref<CookieAccount | null>(null)
const adjustMode = ref<'recharge' | 'deduct'>('recharge')

// ── Options ────────────────────────────────
const statusOptions: SelectOption[] = [
  { label: '全部状态', value: 'all' },
  { label: '正常', value: 'active' },
  { label: '已冻结', value: 'frozen' },
  { label: '已停用', value: 'suspended' },
]

const sortOptions: SelectOption[] = [
  { label: '余额 ↓', value: 'balance' },
  { label: '总消费 ↓', value: 'totalSpent' },
  { label: '最近活跃 ↓', value: 'lastActiveAt' },
]

// ── Computed ───────────────────────────────
const adminAccounts = computed(() => cookieStore.adminAccounts)
const adminAccountTotal = computed(() => cookieStore.adminAccountTotal)
const isLoading = computed(() => cookieStore.isLoading)
const systemStats = computed(() => cookieStore.systemStats)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 20,
  pageCount: Math.ceil(adminAccountTotal.value / (filters.value.pageSize ?? 20)),
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  showQuickJumper: true,
  prefix: () => `共 ${adminAccountTotal.value} 个账户`,
}))

// ── Table Columns ──────────────────────────
const columns = computed<DataTableColumns<CookieAccount>>(() => [
  {
    title: '用户信息',
    key: 'userInfo',
    minWidth: 220,
    render: (row) => h(NSpace, { align: 'center', size: 10 }, {
      default: () => [
        h(NAvatar, {
          src: row.avatar,
          fallbackSrc: '/default-avatar.png',
          round: true,
          size: 36,
        }),
        h('div', {}, [
          h(NText, { strong: true }, { default: () => row.userName }),
          h('br'),
          h(NText, { depth: 3, style: 'font-size: 12px;' }, {
            default: () => row.email,
          }),
        ]),
      ],
    }),
  },
  {
    title: '当前余额',
    key: 'balance',
    width: 130,
    sorter: true,
    align: 'right',
    render: (row) => h(NText, {
      strong: true,
      style: { color: '#f5a623', fontSize: '15px' },
    }, { default: () => `${row.balance.toLocaleString()} 🥫` }),
  },
  {
    title: '总消费',
    key: 'totalSpent',
    width: 130,
    sorter: true,
    align: 'right',
    render: (row) => `${row.totalSpent.toLocaleString()} 🥫`,
  },
  {
    title: '总获得',
    key: 'totalEarned',
    width: 130,
    align: 'right',
    render: (row) => `${row.totalEarned.toLocaleString()} 🥫`,
  },
  {
    title: '账户状态',
    key: 'status',
    width: 110,
    render: (row) => {
      const statusMap: Record<AccountStatus, { type: 'success' | 'error' | 'warning', label: string }> = {
        active: { type: 'success', label: '正常' },
        frozen: { type: 'error', label: '已冻结' },
        suspended: { type: 'warning', label: '已停用' },
      }
      const s = statusMap[row.status]
      return h(NTag, { type: s.type, size: 'small', round: true }, {
        default: () => s.label,
      })
    },
  },
  {
    title: '最后活跃',
    key: 'lastActiveAt',
    width: 170,
    render: (row) => formatDateTime(row.lastActiveAt),
  },
  {
    title: '操作',
    key: 'actions',
    width: 280,
    fixed: 'right',
    render: (row) => h(NSpace, { size: 4 }, {
      default: () => [
        // 充值按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'success',
            ghost: true,
            onClick: () => openAdjustModal(row, 'recharge'),
          }, {
            icon: () => h(NIcon, null, { default: () => h(AddOutline) }),
            default: () => '充值',
          }),
          default: () => '增加用户饼干余额',
        }),
        // 扣减按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'error',
            ghost: true,
            onClick: () => openAdjustModal(row, 'deduct'),
          }, {
            icon: () => h(NIcon, null, { default: () => h(RemoveOutline) }),
            default: () => '扣减',
          }),
          default: () => '减少用户饼干余额',
        }),
        // 冻结/解冻按钮
        h(NPopconfirm, {
          onPositiveClick: () => toggleStatus(row),
        }, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: row.status === 'active' ? 'warning' : 'primary',
            ghost: true,
          }, {
            icon: () => h(NIcon, null, {
              default: () => h(row.status === 'active' ? LockClosedOutline : LockOpenOutline),
            }),
            default: () => row.status === 'active' ? '冻结' : '解冻',
          }),
          default: () => `确定要${row.status === 'active' ? '冻结' : '解冻'}该账户吗？`,
        }),
        // 查看明细按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'info',
            ghost: true,
            onClick: () => viewUserTransactions(row.userId),
          }, {
            icon: () => h(NIcon, null, { default: () => h(EyeOutline) }),
            default: () => '明细',
          }),
          default: () => '查看该用户的交易流水',
        }),
      ],
    }),
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchSystemStats()
  cookieStore.fetchAdminAccounts(filters.value)
  cookieStore.subscribeBalanceUpdates()
})

onUnmounted(() => {
  cookieStore.unsubscribeBalanceUpdates()
})

// ── Methods ────────────────────────────────

function handleSearch() {
  filters.value.page = 1
  cookieStore.fetchAdminAccounts(filters.value)
}

function handleReset() {
  filters.value = {
    search: '',
    status: 'all',
    sortBy: 'balance',
    sortOrder: 'desc',
    page: 1,
    pageSize: 20,
  }
  cookieStore.fetchAdminAccounts(filters.value)
}

function handlePageChange(page: number) {
  filters.value.page = page
  cookieStore.fetchAdminAccounts(filters.value)
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  cookieStore.fetchAdminAccounts(filters.value)
}

function openAdjustModal(user: CookieAccount, mode: 'recharge' | 'deduct') {
  selectedUser.value = user
  adjustMode.value = mode
  showAdjustModal.value = true
}

async function toggleStatus(row: CookieAccount) {
  const newStatus = row.status === 'active' ? 'frozen' : 'active'
  try {
    await cookieStore.toggleAccountStatus(row.userId, newStatus)
    window.$message?.success(`账户已${newStatus === 'active' ? '解冻' : '冻结'}`)
  } catch (err: any) {
    window.$message?.error(err.message || '操作失败')
  }
}

function viewUserTransactions(userId: number) {
  router.push({
    path: '/admin/cookies/transactions',
    query: { userId: String(userId) },
  })
}

function handleAdjustSuccess() {
  cookieStore.fetchAdminAccounts(filters.value)
  cookieStore.fetchSystemStats()
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.admin-cookie-page {
  padding: 20px;
}

.admin-stat-card {
  border-radius: 12px;
  background: linear-gradient(135deg, var(--n-card-color) 0%, var(--n-action-color) 100%);
}

.admin-stat-card :deep(.n-card__content) {
  padding: 16px;
}

.admin-stat-card--danger :deep(.n-statistic-value) {
  color: #d03050;
}

.admin-stat-card--success :deep(.n-statistic-value) {
  color: #18a058;
}

.admin-stat-card--warning :deep(.n-statistic-value) {
  color: #f0a020;
}
</style>
```

---

## 7. CookieAdjustModal.vue

```vue
<!-- components/cookie/CookieAdjustModal.vue -->
<template>
  <n-modal
    v-model:show="show"
    :mask-closable="false"
    preset="card"
    :title="modalTitle"
    :bordered="false"
    class="adjust-modal"
    style="width: 480px;"
  >
    <n-space v-if="user" vertical :size="20">
      <!-- 用户信息 -->
      <n-card embedded size="small">
        <n-space align="center" :size="12">
          <n-avatar
            :src="user.avatar"
            fallback-src="/default-avatar.png"
            round
            size="48"
          />
          <div>
            <n-text strong style="font-size: 16px;">{{ user.userName }}</n-text>
            <br />
            <n-text depth="3" style="font-size: 13px;">{{ user.email }}</n-text>
          </div>
        </n-space>
      </n-card>

      <!-- 当前余额 -->
      <n-descriptions label-placement="left" :column="1" bordered>
        <n-descriptions-item label="当前余额">
          <n-text strong style="color: #f5a623; font-size: 18px;">
            {{ user.balance.toLocaleString() }} 🥫
          </n-text>
        </n-descriptions-item>
        <n-descriptions-item label="操作类型">
          <n-tag :type="mode === 'recharge' ? 'success' : 'error'" size="small" round>
            {{ mode === 'recharge' ? '🔼 充值（增加余额）' : '🔽 扣减（减少余额）' }}
          </n-tag>
        </n-descriptions-item>
      </n-descriptions>

      <!-- 调整表单 -->
      <n-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-placement="left"
        label-width="100"
      >
        <n-form-item label="调整金额" path="amount">
          <n-input-number
            v-model:value="formData.amount"
            :min="mode === 'recharge' ? 1 : undefined"
            :max="mode === 'deduct' ? -1 : undefined"
            :placeholder="mode === 'recharge' ? '请输入充值金额（正数）' : '请输入扣减金额（负数）'"
            style="width: 100%;"
            :show-button="true"
            :precision="0"
          >
            <template #suffix>🥫</template>
          </n-input-number>
        </n-form-item>

        <!-- 变更后余额预览 -->
        <n-form-item label="变更后余额">
          <n-text
            :type="newBalance >= 0 ? 'success' : 'error'"
            strong
            style="font-size: 16px;"
          >
            {{ newBalance.toLocaleString() }} 🥫
          </n-text>
          <n-text v-if="newBalance < 0" type="error" style="margin-left: 8px;">
            余额不能为负数！
          </n-text>
        </n-form-item>

        <n-form-item label="调整原因" path="reason">
          <n-input
            v-model:value="formData.reason"
            type="textarea"
            :rows="3"
            placeholder="请详细说明调整原因（必填）..."
            maxlength="200"
            show-count
          />
        </n-form-item>

        <!-- 二次确认密码 -->
        <n-form-item label="确认密码" path="password">
          <n-input
            v-model:value="formData.password"
            type="password"
            placeholder="请输入您的管理员密码以确认操作"
            show-password-on="mousedown"
          />
        </n-form-item>
      </n-form>

      <!-- 操作记录提示 -->
      <n-alert type="warning" :show-icon="true" size="small">
        此操作将被记录在系统日志中，且不可撤销。请确认金额和原因无误后再提交。
      </n-alert>

      <!-- 按钮 -->
      <n-space justify="end" :size="12">
        <n-button @click="show = false">取消</n-button>
        <n-button
          type="primary"
          :loading="submitting"
          :disabled="!isFormValid"
          @click="handleSubmit"
        >
          确认{{ mode === 'recharge' ? '充值' : '扣减' }}
        </n-button>
      </n-space>
    </n-space>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  NModal, NCard, NSpace, NAvatar, NText, NTag,
  NDescriptions, NDescriptionsItem, NForm, NFormItem,
  NInputNumber, NInput, NAlert, NButton,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieAccount, CookieAdjustParams } from '@/types/cookie'

// ═══════════════════════════════════════════
// Props & Emits
// ═══════════════════════════════════════════

const props = defineProps<{
  show: boolean
  user: CookieAccount | null
  mode: 'recharge' | 'deduct'
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'success': []
}>()

// ═══════════════════════════════════════════
// State
// ═══════════════════════════════════════════

const show = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val),
})

const cookieStore = useCookieStore()
const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

const formData = ref({
  amount: undefined as number | undefined,
  reason: '',
  password: '',
})

// ═══════════════════════════════════════════
// Computed
// ═══════════════════════════════════════════

const modalTitle = computed(() => {
  if (!props.user) return ''
  return props.mode === 'recharge'
    ? `🥫 充值 — ${props.user.userName}`
    : `🥫 扣减 — ${props.user.userName}`
})

const newBalance = computed(() => {
  if (!props.user || formData.value.amount === undefined) return props.user?.balance ?? 0
  const adjustment = props.mode === 'recharge'
    ? Math.abs(formData.value.amount)
    : -Math.abs(formData.value.amount)
  return props.user.balance + adjustment
})

const isFormValid = computed(() => {
  return (
    formData.value.amount !== undefined &&
    formData.value.amount !== 0 &&
    formData.value.reason.trim().length > 0 &&
    formData.value.password.length > 0 &&
    newBalance.value >= 0
  )
})

// ═══════════════════════════════════════════
// Form Rules
// ═══════════════════════════════════════════

const formRules: FormRules = {
  amount: [
    { required: true, message: '请输入调整金额', trigger: ['blur', 'input'], type: 'number' },
    {
      validator: (_rule, value: number) => {
        if (props.mode === 'recharge' && value <= 0) {
          return new Error('充值金额必须大于0')
        }
        if (props.mode === 'deduct' && value >= 0) {
          return new Error('扣减金额必须小于0')
        }
        return true
      },
      trigger: ['blur', 'input'],
    },
  ],
  reason: [
    { required: true, message: '请输入调整原因', trigger: 'blur' },
    { min: 2, max: 200, message: '原因长度为2-200字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入确认密码', trigger: 'blur' },
  ],
}

// ═══════════════════════════════════════════
// Watch
// ═══════════════════════════════════════════

watch(() => props.show, (val) => {
  if (val) {
    // 打开弹窗时重置表单
    formData.value = {
      amount: props.mode === 'recharge' ? undefined : undefined,
      reason: '',
      password: '',
    }
  }
})

watch(() => props.mode, () => {
  formData.value.amount = undefined
})

// ═══════════════════════════════════════════
// Methods
// ═══════════════════════════════════════════

async function handleSubmit() {
  if (!formRef.value) return

  await formRef.value.validate(async (errors) => {
    if (errors) return
    if (!props.user) return

    submitting.value = true
    try {
      const adjustAmount = props.mode === 'recharge'
        ? Math.abs(formData.value.amount!)
        : -Math.abs(formData.value.amount!)

      const params: CookieAdjustParams = {
        userId: props.user.userId,
        amount: adjustAmount,
        reason: formData.value.reason,
        password: formData.value.password,
      }

      await cookieStore.adjustBalance(params)

      window.$message?.success(
        `${props.mode === 'recharge' ? '充值' : '扣减'}成功！余额已更新。`
      )
      show.value = false
      emit('success')
    } catch (err: any) {
      window.$message?.error(err.message || '操作失败')
    } finally {
      submitting.value = false
    }
  })
}
</script>

<style scoped>
.adjust-modal :deep(.n-card-header) {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.adjust-modal :deep(.n-card__content) {
  padding: 20px;
}
</style>
```


---

## 8. AdminCookieTransactionsView.vue

```vue
<!-- views/admin/AdminCookieTransactionsView.vue -->
<template>
  <div class="admin-transactions-page">
    <n-page-header title="🧾 交易流水查询" subtitle="查看和管理全站饼干交易记录" />

    <!-- 面包屑导航 -->
    <n-breadcrumb style="margin-top: 8px;">
      <n-breadcrumb-item @click="router.push('/admin/cookies')">
        饼干管理
      </n-breadcrumb-item>
      <n-breadcrumb-item>交易流水</n-breadcrumb-item>
    </n-breadcrumb>

    <n-card :bordered="false" style="margin-top: 16px;">
      <!-- ═══════════ 高级筛选栏 ═══════════ -->
      <n-card title="🔍 筛选条件" embedded size="small" style="margin-bottom: 16px;">
        <n-grid :cols="4" :x-gap="12" :y-gap="12" responsive="screen">
          <n-grid-item span="4 s:2 m:1">
            <n-input
              v-model:value="filters.searchUser"
              placeholder="用户名 / 邮箱"
              clearable
            >
              <template #prefix>
                <n-icon><PersonOutline /></n-icon>
              </template>
            </n-input>
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-select
              v-model:value="filters.type"
              :options="typeOptions"
              placeholder="交易类型"
              clearable
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-date-picker
              v-model:formatted-value="filters.startDate"
              type="datetime"
              placeholder="开始时间"
              value-format="yyyy-MM-dd HH:mm:ss"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-date-picker
              v-model:formatted-value="filters.endDate"
              type="datetime"
              placeholder="结束时间"
              value-format="yyyy-MM-dd HH:mm:ss"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-input-number
              v-model:value="filters.minAmount"
              placeholder="最小金额"
              :min="0"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-input-number
              v-model:value="filters.maxAmount"
              placeholder="最大金额"
              :min="0"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:4 m:2">
            <n-space>
              <n-button type="primary" @click="handleSearch">
                <template #icon><n-icon><SearchOutline /></n-icon></template>
                查询
              </n-button>
              <n-button @click="handleReset">重置</n-button>
              <n-button type="info" ghost @click="handleExport">
                <template #icon><n-icon><DownloadOutline /></n-icon></template>
                导出 CSV
              </n-button>
            </n-space>
          </n-grid-item>
        </n-grid>
      </n-card>

      <!-- ═══════════ 统计汇总 ═══════════ -->
      <n-space :size="24" style="margin-bottom: 16px;">
        <n-statistic label="查询结果" tabular-nums>
          <n-number-animation :from="0" :to="transactionTotal" show-separator />
          <template #suffix>条</template>
        </n-statistic>
        <n-statistic label="收入合计" tabular-nums>
          <n-text type="success">
            <n-number-animation :from="0" :to="stats.income" show-separator />
          </n-text>
          <template #suffix>🥫</template>
        </n-statistic>
        <n-statistic label="支出合计" tabular-nums>
          <n-text type="error">
            <n-number-animation :from="0" :to="stats.expense" show-separator />
          </n-text>
          <template #suffix>🥫</template>
        </n-statistic>
      </n-space>

      <!-- ═══════════ 流水表格 ═══════════ -->
      <n-data-table
        :columns="columns"
        :data="transactions"
        :loading="isLoading"
        :pagination="pagination"
        :row-key="(row: CookieTransaction) => row.id"
        @update:page="handlePageChange"
        @update:page-size="handlePageSizeChange"
      />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NPageHeader, NBreadcrumb, NBreadcrumbItem, NCard, NGrid, NGridItem,
  NInput, NSelect, NDatePicker, NInputNumber, NButton, NSpace,
  NDataTable, NText, NTag, NIcon, NEllipsis, NStatistic,
  NNumberAnimation,
} from 'naive-ui'
import {
  PersonOutline, SearchOutline, DownloadOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType, TransactionFilters } from '@/types/cookie'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const route = useRoute()
const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const filters = ref<TransactionFilters & { searchUser?: string }>({
  searchUser: '',
  type: 'all',
  startDate: undefined,
  endDate: undefined,
  minAmount: undefined,
  maxAmount: undefined,
  page: 1,
  pageSize: 50,
})

const stats = ref({ income: 0, expense: 0 })

// ── Options ────────────────────────────────
const typeOptions: SelectOption[] = [
  { label: '全部类型', value: 'all' },
  { label: '获得', value: 'earn' },
  { label: '消费', value: 'spend' },
  { label: '调整', value: 'adjust' },
  { label: '退款', value: 'refund' },
  { label: '充值', value: 'recharge' },
]

// ── Computed ───────────────────────────────
const transactions = computed(() => cookieStore.transactions)
const transactionTotal = computed(() => cookieStore.transactionTotal)
const isLoading = computed(() => cookieStore.isLoading)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 50,
  pageCount: Math.ceil(transactionTotal.value / (filters.value.pageSize ?? 50)),
  showSizePicker: true,
  pageSizes: [20, 50, 100, 200],
  showQuickJumper: true,
  prefix: () => `共 ${transactionTotal.value} 条`,
}))

// ── Columns ────────────────────────────────
const columns = computed<DataTableColumns<CookieTransaction>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 70,
  },
  {
    title: '用户',
    key: 'userName',
    width: 130,
    render: (row) => h(NEllipsis, null, { default: () => row.userName }),
  },
  {
    title: '时间',
    key: 'createdAt',
    width: 170,
    render: (row) => formatDateTime(row.createdAt),
  },
  {
    title: '类型',
    key: 'type',
    width: 90,
    render: (row) => h(NTag, {
      type: getTxTagType(row.type),
      size: 'small',
      round: true,
    }, { default: () => getTxLabel(row.type) }),
  },
  {
    title: '金额',
    key: 'amount',
    width: 110,
    align: 'right',
    render: (row) => h(NText, {
      strong: true,
      type: row.amount > 0 ? 'success' : 'error',
    }, { default: () => `${row.amount > 0 ? '+' : ''}${row.amount} 🥫` }),
  },
  {
    title: '变动后余额',
    key: 'balanceAfter',
    width: 120,
    align: 'right',
    render: (row) => `${row.balanceAfter.toLocaleString()} 🥫`,
  },
  {
    title: '描述',
    key: 'description',
    minWidth: 200,
    render: (row) => h(NEllipsis, { style: 'max-width: 280px;' }, {
      default: () => row.description,
    }),
  },
  {
    title: '关联任务',
    key: 'relatedTaskId',
    width: 100,
    render: (row) => row.relatedTaskId
      ? h(NButton, { text: true, type: 'info', size: 'tiny' }, {
          default: () => `#${row.relatedTaskId}`,
        })
      : '--',
  },
  {
    title: '操作者',
    key: 'operatorName',
    width: 110,
    render: (row) => row.operatorName || '系统',
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  // 如果从用户管理页跳转过来，自动填入用户ID
  const userId = route.query.userId
  if (userId) {
    filters.value.searchUser = String(userId)
  }
  handleSearch()
})

// ── Methods ────────────────────────────────

function handleSearch() {
  filters.value.page = 1
  // 同时计算统计
  calculateStats()
  cookieStore.fetchTransactions({
    type: filters.value.type === 'all' ? undefined : filters.value.type as TransactionType,
    startDate: filters.value.startDate,
    endDate: filters.value.endDate,
    minAmount: filters.value.minAmount,
    maxAmount: filters.value.maxAmount,
    page: filters.value.page,
    pageSize: filters.value.pageSize,
  })
}

function handleReset() {
  filters.value = {
    searchUser: '',
    type: 'all',
    startDate: undefined,
    endDate: undefined,
    minAmount: undefined,
    maxAmount: undefined,
    page: 1,
    pageSize: 50,
  }
  handleSearch()
}

function handlePageChange(page: number) {
  filters.value.page = page
  handleSearch()
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  handleSearch()
}

function handleExport() {
  // CSV 导出
  const headers = ['ID', '用户', '时间', '类型', '金额', '余额', '描述', '操作者']
  const rows = transactions.value.map(tx => [
    tx.id,
    tx.userName,
    tx.createdAt,
    tx.type,
    tx.amount,
    tx.balanceAfter,
    tx.description,
    tx.operatorName || '系统',
  ])
  const csv = [headers, ...rows]
    .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
    .join('\n')

  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `cookie-transactions-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)

  window.$message?.success('CSV 导出成功')
}

function calculateStats() {
  // 计算收入/支出合计（基于当前查询结果）
  const income = transactions.value
    .filter(t => t.amount > 0)
    .reduce((sum, t) => sum + t.amount, 0)
  const expense = transactions.value
    .filter(t => t.amount < 0)
    .reduce((sum, t) => sum + Math.abs(t.amount), 0)
  stats.value = { income, expense }
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getTxTagType(type: TransactionType) {
  const map: Record<string, 'success' | 'error' | 'info' | 'warning' | 'default'> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得', spend: '消费', adjust: '调整',
    refund: '退款', recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.admin-transactions-page {
  padding: 20px;
}
</style>
```

---

## 9. AdminCookiePricingView.vue

```vue
<!-- views/admin/AdminCookiePricingView.vue -->
<template>
  <div class="admin-pricing-page">
    <n-page-header title="🏷️ 定价策略管理" subtitle="管理系统资源定价与计费规则" />

    <n-breadcrumb style="margin-top: 8px;">
      <n-breadcrumb-item @click="router.push('/admin/cookies')">
        饼干管理
      </n-breadcrumb-item>
      <n-breadcrumb-item>定价策略</n-breadcrumb-item>
    </n-breadcrumb>

    <n-card :bordered="false" style="margin-top: 16px;">
      <!-- 新增按钮 -->
      <n-space justify="space-between" align="center" style="margin-bottom: 16px;">
        <n-text depth="3">配置各任务类型的资源单价，影响任务提交时的费用预估</n-text>
        <n-button type="primary" @click="openCreateModal">
          <template #icon><n-icon><AddOutline /></n-icon></template>
          新增定价策略
        </n-button>
      </n-space>

      <!-- 定价表格 -->
      <n-data-table
        :columns="columns"
        :data="pricingList"
        :loading="isLoading"
        :row-key="(row: CookiePricing) => row.id"
        :pagination="false"
      />
    </n-card>

    <!-- ═══════════ 新增/编辑弹窗 ═══════════ -->
    <n-modal
      v-model:show="showModal"
      preset="card"
      :title="isEdit ? '✏️ 编辑定价策略' : '➕ 新增定价策略'"
      style="width: 500px;"
      :bordered="false"
      :mask-closable="false"
    >
      <n-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-placement="left"
        label-width="110"
      >
        <n-form-item label="任务类型" path="flowCategory">
          <n-select
            v-model:value="formData.flowCategory"
            :options="flowCategoryOptions"
            placeholder="选择任务类型"
            :disabled="isEdit"
          />
        </n-form-item>

        <n-form-item label="资源类型" path="resourceType">
          <n-select
            v-model:value="formData.resourceType"
            :options="resourceTypeOptions"
            placeholder="选择资源类型"
            :disabled="isEdit"
          />
        </n-form-item>

        <n-form-item label="单价" path="unitPrice">
          <n-input-number
            v-model:value="formData.unitPrice"
            :min="0"
            :precision="2"
            placeholder="每小时单价（饼干）"
            style="width: 100%;"
          >
            <template #suffix>🥫 / 小时</template>
          </n-input-number>
        </n-form-item>

        <n-form-item label="描述" path="description">
          <n-input
            v-model:value="formData.description"
            type="textarea"
            :rows="2"
            placeholder="定价策略说明..."
            maxlength="200"
            show-count
          />
        </n-form-item>

        <n-form-item label="生效时间" path="effectiveFrom">
          <n-date-picker
            v-model:formatted-value="formData.effectiveFrom"
            type="datetime"
            placeholder="生效时间"
            value-format="yyyy-MM-dd HH:mm:ss"
            style="width: 100%;"
          />
        </n-form-item>

        <n-form-item label="过期时间" path="effectiveTo">
          <n-date-picker
            v-model:formatted-value="formData.effectiveTo"
            type="datetime"
            placeholder="留空表示长期有效"
            value-format="yyyy-MM-dd HH:mm:ss"
            clearable
            style="width: 100%;"
          />
        </n-form-item>
      </n-form>

      <template #footer>
        <n-space justify="end" :size="12">
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            {{ isEdit ? '保存修改' : '创建策略' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NBreadcrumb, NBreadcrumbItem, NCard, NSpace,
  NButton, NDataTable, NText, NTag, NIcon, NModal, NForm,
  NFormItem, NSelect, NInputNumber, NInput, NDatePicker,
  NSwitch, NPopconfirm,
} from 'naive-ui'
import type { FormInst, FormRules, DataTableColumns, SelectOption } from 'naive-ui'
import { AddOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookiePricing, PricingFormData, FlowCategory, ResourceType } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const showModal = ref(false)
const isEdit = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

const formData = ref<PricingFormData>({
  flowCategory: 'rna_seq',
  resourceType: 'cpu',
  unitPrice: 0,
  description: '',
  effectiveFrom: new Date().toISOString().slice(0, 19).replace('T', ' '),
  effectiveTo: undefined,
})

// ── Options ────────────────────────────────
const flowCategoryOptions: SelectOption[] = [
  { label: 'RNA-seq', value: 'rna_seq' },
  { label: 'ChIP-seq', value: 'chip_seq' },
  { label: 'ATAC-seq', value: 'atac_seq' },
  { label: 'WGS', value: 'wgs' },
  { label: 'Proteomics', value: 'proteomics' },
  { label: 'Metabolomics', value: 'metabolomics' },
  { label: 'scRNA-seq', value: 'sc_rna_seq' },
  { label: 'Data Integration', value: 'data_integration' },
]

const resourceTypeOptions: SelectOption[] = [
  { label: 'CPU', value: 'cpu' },
  { label: '内存', value: 'memory' },
  { label: 'GPU', value: 'gpu' },
]

const flowCategoryLabel = (v: FlowCategory) =>
  flowCategoryOptions.find(o => o.value === v)?.label ?? v

const resourceTypeLabel = (v: ResourceType) =>
  resourceTypeOptions.find(o => o.value === v)?.label ?? v

// ── Computed ───────────────────────────────
const pricingList = computed(() => cookieStore.pricing)
const isLoading = computed(() => cookieStore.isLoading)

// ── Columns ────────────────────────────────
const columns = computed<DataTableColumns<CookiePricing>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 60,
  },
  {
    title: '任务类型',
    key: 'flowCategory',
    width: 140,
    render: (row) => h(NTag, { type: 'info', size: 'small' }, {
      default: () => flowCategoryLabel(row.flowCategory),
    }),
  },
  {
    title: '资源类型',
    key: 'resourceType',
    width: 100,
    render: (row) => resourceTypeLabel(row.resourceType),
  },
  {
    title: '单价',
    key: 'unitPrice',
    width: 130,
    align: 'right',
    render: (row) => h(NText, { strong: true }, {
      default: () => `${row.unitPrice} 🥫/小时`,
    }),
  },
  {
    title: '描述',
    key: 'description',
    minWidth: 200,
    render: (row) => h(NText, { depth: 2 }, { default: () => row.description }),
  },
  {
    title: '生效时间',
    key: 'effectiveFrom',
    width: 170,
    render: (row) => formatDateTime(row.effectiveFrom),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => h(NSwitch, {
      value: row.status === 'active',
      onUpdateValue: (val: boolean) => handleToggleStatus(row.id, val),
    }, {
      checked: () => '生效',
      unchecked: () => '停用',
    }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    fixed: 'right',
    render: (row) => h(NButton, {
      size: 'tiny',
      type: 'primary',
      ghost: true,
      onClick: () => openEditModal(row),
    }, { default: () => '编辑' }),
  },
])

// ── Form Rules ─────────────────────────────
const formRules: FormRules = {
  flowCategory: [{ required: true, message: '请选择任务类型', trigger: 'blur', type: 'string' }],
  resourceType: [{ required: true, message: '请选择资源类型', trigger: 'blur', type: 'string' }],
  unitPrice: [
    { required: true, message: '请输入单价', trigger: 'blur', type: 'number' },
    { min: 0, message: '单价不能为负数', trigger: 'blur', type: 'number' },
  ],
  effectiveFrom: [{ required: true, message: '请选择生效时间', trigger: 'blur', type: 'string' }],
}

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchPricing()
})

// ── Methods ────────────────────────────────

function openCreateModal() {
  isEdit.value = false
  editingId.value = null
  formData.value = {
    flowCategory: 'rna_seq',
    resourceType: 'cpu',
    unitPrice: 0,
    description: '',
    effectiveFrom: new Date().toISOString().slice(0, 19).replace('T', ' '),
    effectiveTo: undefined,
  }
  showModal.value = true
}

function openEditModal(pricing: CookiePricing) {
  isEdit.value = true
  editingId.value = pricing.id
  formData.value = {
    flowCategory: pricing.flowCategory,
    resourceType: pricing.resourceType,
    unitPrice: pricing.unitPrice,
    description: pricing.description,
    effectiveFrom: pricing.effectiveFrom,
    effectiveTo: pricing.effectiveTo,
  }
  showModal.value = true
}

async function handleToggleStatus(id: number, active: boolean) {
  try {
    await cookieStore.togglePricingStatus(id, active ? 'active' : 'inactive')
    window.$message?.success(active ? '定价策略已生效' : '定价策略已停用')
  } catch (err: any) {
    window.$message?.error(err.message || '操作失败')
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (errors) => {
    if (errors) return

    submitting.value = true
    try {
      if (isEdit.value && editingId.value) {
        await cookieStore.updatePricing(editingId.value, formData.value)
        window.$message?.success('定价策略已更新')
      } else {
        await cookieStore.createPricing(formData.value)
        window.$message?.success('定价策略已创建')
      }
      showModal.value = false
    } catch (err: any) {
      window.$message?.error(err.message || '操作失败')
    } finally {
      submitting.value = false
    }
  })
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.admin-pricing-page {
  padding: 20px;
}
</style>
```

---

## 10. TaskSubmitView.vue 饼干预估更新

```vue
<!-- views/task/TaskSubmitView.vue — 饼干预估区域（嵌入在提交表单底部） -->

<!-- ═══════════ 在 TaskSubmitView.vue 的 <template> 中，提交按钮上方插入 ═══════════ -->
<template>
  <!-- ... 原有表单内容 ... -->

  <!-- 🥫 饼干预估区域 -->
  <n-card
    size="small"
    class="cost-estimate-card"
    :bordered="false"
  >
    <template #header>
      <n-space align="center" :size="8">
        <n-icon size="18" color="#f5a623"><CookieOutline /></n-icon>
        <n-text strong>饼干预估</n-text>
        <n-tag v-if="estimate" size="tiny" type="warning" round>
          实时计算
        </n-tag>
      </n-space>
    </template>

    <n-space vertical :size="12">
      <!-- 费用明细 -->
      <n-skeleton v-if="!estimate && isEstimating" text :repeat="4" />

      <template v-else-if="estimate">
        <!-- 基础费用 -->
        <n-space justify="space-between" align="center">
          <n-text depth="2">
            基础费用（{{ flowCategoryLabel }}）
          </n-text>
          <n-text>{{ estimate.baseFee }} 🥫</n-text>
        </n-space>

        <!-- 资源费用明细 -->
        <n-space
          v-for="res in estimate.resources"
          :key="res.resourceType"
          justify="space-between"
          align="center"
        >
          <n-text depth="2">
            {{ resourceLabel(res.resourceType) }}
            <n-text depth="3" style="font-size: 12px;">
              （{{ res.quantity }}{{ resourceUnit(res.resourceType) }} × {{ res.duration }}小时 @ {{ res.unitPrice }}🥫/h）
            </n-text>
          </n-text>
          <n-text>{{ res.subtotal }} 🥫</n-text>
        </n-space>

        <!-- 折扣信息 -->
        <n-space
          v-if="estimate.discountRate < 1"
          justify="space-between"
          align="center"
        >
          <n-text depth="2" type="success">
            折扣优惠（{{ (estimate.discountRate * 10).toFixed(1) }}折）
          </n-text>
          <n-text type="success">
            -{{ (estimate.total - estimate.discountedTotal).toFixed(0) }} 🥫
          </n-text>
        </n-space>

        <n-divider style="margin: 8px 0;" />

        <!-- 预估总计 -->
        <n-space justify="space-between" align="center">
          <n-text strong style="font-size: 15px;">预估总计</n-text>
          <n-text type="warning" strong style="font-size: 18px;">
            {{ Math.ceil(estimate.discountedTotal) }} 🥫
          </n-text>
        </n-space>
      </template>

      <n-empty
        v-else
        description="选择任务类型和资源后显示预估费用"
        size="small"
      />

      <n-divider style="margin: 8px 0;" />

      <!-- 余额检查 -->
      <n-alert
        v-if="account && estimate && account.balance < estimate.discountedTotal"
        type="error"
        :show-icon="true"
      >
        <n-space vertical :size="4">
          <n-text strong>余额不足！</n-text>
          <n-text>
            当前余额 <n-text strong>{{ account.balance }}</n-text> 🥫，
            还需 <n-text type="error" strong>{{ Math.ceil(estimate.discountedTotal - account.balance) }}</n-text> 🥫
          </n-text>
          <n-button
            text
            type="primary"
            size="small"
            @click="goToAccount"
          >
            前往饼干账户 →
          </n-button>
        </n-space>
      </n-alert>

      <n-space
        v-else-if="account && estimate"
        justify="space-between"
        align="center"
      >
        <n-space align="center" :size="8">
          <n-icon size="16" color="#f5a623"><CookieOutline /></n-icon>
          <n-text depth="2">当前余额</n-text>
        </n-space>
        <n-text>
          <n-text strong style="color: #f5a623;">{{ account.balance }}</n-text>
          🥫（执行后剩余 <n-text strong>{{ account.balance - Math.ceil(estimate.discountedTotal) }}</n-text> 🥫）
        </n-text>
      </n-space>
    </n-space>
  </n-card>

  <!-- 提交按钮 -->
  <n-space justify="end" style="margin-top: 16px;">
    <n-button
      type="primary"
      size="large"
      :disabled="!canSubmit"
      :loading="submitting"
      @click="handleSubmit"
    >
      <template #icon><n-icon><SendOutline /></n-icon></template>
      提交任务（{{ estimate ? Math.ceil(estimate.discountedTotal) + ' 🥫' : '...' }}）
    </n-button>
  </n-space>

  <!-- ═══════════ 余额不足弹窗 ═══════════ -->
  <n-modal
    v-model:show="showInsufficientModal"
    preset="card"
    title="🥫 饼干余额不足"
    style="width: 420px;"
    :bordered="false"
  >
    <n-space vertical align="center" :size="20">
      <n-icon size="64" color="#f5a623" class="cookie-large-icon">
        <CookieOutline />
      </n-icon>

      <n-text style="font-size: 16px;">
        您的饼干余额不足，无法提交此任务。
      </n-text>

      <n-descriptions bordered :column="1" style="width: 100%;">
        <n-descriptions-item label="当前余额">
          <n-text strong style="color: #f5a623;">{{ account?.balance ?? 0 }} 🥫</n-text>
        </n-descriptions-item>
        <n-descriptions-item label="预估消耗">
          <n-text strong type="error">
            {{ estimate ? Math.ceil(estimate.discountedTotal) : '--' }} 🥫
          </n-text>
        </n-descriptions-item>
        <n-descriptions-item label="差额">
          <n-text strong type="error">
            {{ estimate && account ? Math.ceil(estimate.discountedTotal - account.balance) : '--' }} 🥫
          </n-text>
        </n-descriptions-item>
      </n-descriptions>

      <n-text depth="3" style="font-size: 13px;">
        请联系管理员充值饼干，或前往饼干账户页面查看详情。
      </n-text>

      <n-space :size="12">
        <n-button @click="showInsufficientModal = false">取消</n-button>
        <n-button type="primary" @click="goToAccount">
          前往饼干账户
        </n-button>
      </n-space>
    </n-space>
  </n-modal>
</template>

<script setup lang="ts">
// ═══════════════════════════════════════════
// 在 TaskSubmitView.vue 的 <script setup> 中新增
// ═══════════════════════════════════════════

import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NSpace, NText, NTag, NIcon, NDivider, NAlert,
  NButton, NModal, NDescriptions, NDescriptionsItem, NSkeleton, NEmpty,
} from 'naive-ui'
import { CookieOutline, SendOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { FlowCategory, ResourceType, EstimateParams } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const showInsufficientModal = ref(false)
const isEstimating = ref(false)
const estimateDebounceTimer = ref<ReturnType<typeof setTimeout> | null>(null)

// 表单数据（从原有 TaskSubmitView 中获取或传入）
const formData = ref({
  flowCategory: 'rna_seq' as FlowCategory,
  cpuCores: 8,
  memoryGb: 16,
  gpuCards: 0,
  estimatedHours: 2,
})

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const estimate = computed(() => cookieStore.estimate)

const flowCategoryLabel = computed(() => {
  const labels: Record<FlowCategory, string> = {
    rna_seq: 'RNA-seq',
    chip_seq: 'ChIP-seq',
    atac_seq: 'ATAC-seq',
    wgs: 'WGS',
    proteomics: 'Proteomics',
    metabolomics: 'Metabolomics',
    sc_rna_seq: 'scRNA-seq',
    data_integration: 'Data Integration',
  }
  return labels[formData.value.flowCategory] ?? formData.value.flowCategory
})

const canSubmit = computed(() => {
  if (!estimate.value || !account.value) return false
  return account.value.balance >= estimate.value.discountedTotal &&
         account.value.status === 'active'
})

// ── Watch — 实时计算预估费用 ────────────────

// 监听资源参数变化，防抖调用预估接口
watch(
  () => [
    formData.value.flowCategory,
    formData.value.cpuCores,
    formData.value.memoryGb,
    formData.value.gpuCards,
    formData.value.estimatedHours,
  ],
  () => {
    isEstimating.value = true
    if (estimateDebounceTimer.value) clearTimeout(estimateDebounceTimer.value)
    estimateDebounceTimer.value = setTimeout(() => {
      refreshEstimate()
    }, 500)
  },
  { immediate: true, deep: true }
)

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchAccount()
})

onUnmounted(() => {
  cookieStore.clearEstimate()
  if (estimateDebounceTimer.value) clearTimeout(estimateDebounceTimer.value)
})

// ── Methods ────────────────────────────────

/** 刷新费用预估 */
async function refreshEstimate() {
  try {
    const params: EstimateParams = {
      flowCategory: formData.value.flowCategory,
      cpuCores: formData.value.cpuCores,
      memoryGb: formData.value.memoryGb,
      gpuCards: formData.value.gpuCards || undefined,
      estimatedHours: formData.value.estimatedHours,
    }
    await cookieStore.estimateTaskCost(params)
  } catch (err) {
    console.error('费用预估失败:', err)
  } finally {
    isEstimating.value = false
  }
}

/** 提交任务 */
async function handleSubmit() {
  // 余额检查
  if (!account.value || !estimate.value) return
  if (account.value.balance < estimate.value.discountedTotal) {
    showInsufficientModal.value = true
    return
  }
  if (account.value.status !== 'active') {
    window.$message?.error('账户已被冻结，无法提交任务')
    return
  }

  // 执行原有提交逻辑...
  // await submitTask()
}

/** 跳转到饼干账户 */
function goToAccount() {
  showInsufficientModal.value = false
  router.push('/cookies/account')
}

/** 资源标签 */
function resourceLabel(type: ResourceType): string {
  const labels: Record<ResourceType, string> = {
    cpu: 'CPU',
    memory: '内存',
    gpu: 'GPU',
  }
  return labels[type] ?? type
}

/** 资源单位 */
function resourceUnit(type: ResourceType): string {
  const units: Record<ResourceType, string> = {
    cpu: '核',
    memory: 'GB',
    gpu: '卡',
  }
  return units[type] ?? ''
}
</script>

<style scoped>
.cost-estimate-card {
  background: linear-gradient(135deg, rgba(245, 166, 35, 0.05) 0%, rgba(245, 166, 35, 0.01) 100%);
  border: 1px solid rgba(245, 166, 35, 0.15);
  border-radius: 10px;
}

.cost-estimate-card :deep(.n-card-header) {
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(245, 166, 35, 0.1);
}

.cookie-large-icon {
  animation: gentle-float 3s ease-in-out infinite;
}

@keyframes gentle-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
</style>
```

---

## 11. 路由配置

```typescript
// router/index.ts — 在现有路由配置中新增以下路由

import type { RouteRecordRaw } from 'vue-router'

const cookieRoutes: RouteRecordRaw[] = [
  // ── 用户饼干账户 ─────────────────────────
  {
    path: '/cookies/account',
    name: 'CookieAccount',
    component: () => import('@/views/cookie/CookieAccountView.vue'),
    meta: {
      requiresAuth: true,
      title: '我的饼干',
      icon: 'CookieOutline',
    },
  },

  // ── 管理员：饼干管理 ─────────────────────
  {
    path: '/admin/cookies',
    name: 'AdminCookieManagement',
    component: () => import('@/views/admin/AdminCookieManagementView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '饼干管理',
      icon: 'CookieOutline',
      menuGroup: 'admin',
    },
  },
  {
    path: '/admin/cookies/transactions',
    name: 'AdminCookieTransactions',
    component: () => import('@/views/admin/AdminCookieTransactionsView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '交易流水',
      icon: 'ListOutline',
      menuGroup: 'admin',
      hiddenInMenu: true, // 不在侧边栏显示，通过饼干管理页面进入
    },
  },
  {
    path: '/admin/cookies/pricing',
    name: 'AdminCookiePricing',
    component: () => import('@/views/admin/AdminCookiePricingView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '定价策略',
      icon: 'PricetagOutline',
      menuGroup: 'admin',
      hiddenInMenu: true,
    },
  },
]

// 合并到主路由
export const routes: RouteRecordRaw[] = [
  // ... 现有路由 ...
  ...cookieRoutes,
]

// 侧边栏菜单配置（AdminLayout）
export const adminMenuOptions = [
  // ... 现有菜单 ...
  {
    label: '饼干管理',
    key: 'cookie-management',
    icon: () => h(NIcon, null, { default: () => h(CookieOutline) }),
    children: [
      {
        label: () => h(RouterLink, { to: '/admin/cookies' }, { default: () => '账户管理' }),
        key: 'admin-cookies',
        icon: () => h(NIcon, null, { default: () => h(PeopleOutline) }),
      },
      {
        label: () => h(RouterLink, { to: '/admin/cookies/transactions' }, { default: () => '交易流水' }),
        key: 'admin-cookies-transactions',
        icon: () => h(NIcon, null, { default: () => h(ListOutline) }),
      },
      {
        label: () => h(RouterLink, { to: '/admin/cookies/pricing' }, { default: () => '定价策略' }),
        key: 'admin-cookies-pricing',
        icon: () => h(NIcon, null, { default: () => h(PricetagOutline) }),
      },
    ],
  },
]
```

---

## 12. API 接口清单

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/v1/cookies/account` | 获取当前用户账户信息 | 登录用户 |
| `GET` | `/api/v1/cookies/account/summary` | 获取账户统计摘要 | 登录用户 |
| `GET` | `/api/v1/cookies/transactions` | 获取交易流水（带筛选） | 登录用户 |
| `GET` | `/api/v1/cookies/account/stats` | 获取图表统计数据 | 登录用户 |
| `POST` | `/api/v1/cookies/estimate` | 预估任务费用 | 登录用户 |
| `GET` | `/api/v1/admin/cookies/statistics` | 获取系统统计 | 管理员 |
| `GET` | `/api/v1/admin/cookies/accounts` | 获取用户账户列表 | 管理员 |
| `POST` | `/api/v1/admin/cookies/accounts/:userId/adjust` | 调整用户余额 | 管理员 |
| `PUT` | `/api/v1/admin/cookies/accounts/:userId/status` | 修改账户状态 | 管理员 |
| `GET` | `/api/v1/admin/cookies/pricing` | 获取定价策略列表 | 管理员 |
| `POST` | `/api/v1/admin/cookies/pricing` | 创建定价策略 | 管理员 |
| `PUT` | `/api/v1/admin/cookies/pricing/:id` | 更新定价策略 | 管理员 |

---

## 13. 组件文件清单

```
src/
├── types/
│   └── cookie.d.ts                    # TypeScript 类型定义
├── stores/
│   └── modules/
│       └── cookie.ts                  # Pinia Store
├── composables/
│   └── useWebSocket.ts               # WebSocket 封装
├── components/
│   └── cookie/
│       ├── CookieBalanceBadge.vue    # Header 饼干余额显示
│       └── CookieAdjustModal.vue     # 管理员充值/扣减弹窗
├── views/
│   ├── cookie/
│   │   └── CookieAccountView.vue     # 用户饼干账户页
│   └── admin/
│       ├── AdminCookieManagementView.vue      # 管理员账户管理
│       ├── AdminCookieTransactionsView.vue    # 交易流水查询
│       └── AdminCookiePricingView.vue         # 定价策略管理
└── router/
    └── index.ts                       # 路由配置（新增饼干路由）
```

---

## 14. 暗黑模式适配说明

所有组件遵循以下暗黑模式适配原则：

1. **使用 Naive UI CSS 变量**：`var(--n-card-color)`、`var(--n-text-color)`、`var(--n-border-color)` 等自动响应主题切换
2. **ECharts 图表适配**：通过 `textStyle: { color: 'var(--n-text-color)' }` 注入主题颜色
3. **自定义颜色使用透明度**：如饼干主题色 `#f5a623` 在不同主题下保持可读性
4. **卡片背景渐变**：使用 `rgba(245, 166, 35, 0.05)` 等低透明度确保暗色下不突兀
5. **Naive UI 自动处理**：`NTag`、`NAlert`、`NButton` 等组件自动适配暗黑模式

---

## 15. 关键交互流程图

```
用户打开页面
  ├── Header 加载 CookieBalanceBadge
  │     ├── 连接 WebSocket /ws/cookies
  │     ├── 获取账户信息 GET /api/v1/cookies/account
  │     └── 获取最近3笔交易 GET /api/v1/cookies/transactions?pageSize=3
  │
  ├── 用户调整任务参数
  │     └── 防抖500ms → POST /api/v1/cookies/estimate
  │           └── 实时更新预估费用显示
  │
  ├── 用户点击"提交任务"
  │     ├── 余额充足？→ 正常提交
  │     └── 余额不足？→ 显示余额不足弹窗 → 引导到账户页
  │
  ├── 任务执行完成
  │     └── WebSocket 推送 cookie.balance_updated
  │           └── CookieBalanceBadge 弹跳动画 + 余额更新
  │
  └── 用户点击饼干图标
        └── 跳转 /cookies/account
              ├── 统计卡片（余额/消费/排名）
              ├── ECharts 图表（趋势/构成）
              └── 交易流水表格（筛选/分页）

管理员操作
  ├── 打开 /admin/cookies
  │     ├── 统计概览卡片
  │     ├── 用户账户表格（搜索/排序/分页）
  │     └── 操作：充值/扣减/冻结/查看明细
  │
  ├── 点击"充值/扣减"
  │     └── CookieAdjustModal 弹窗
  │           ├── 输入金额（实时预览变更后余额）
  │           ├── 输入原因（必填）
  │           ├── 输入管理员密码（二次确认）
  │           └── 提交 → POST /api/v1/admin/cookies/accounts/:id/adjust
  │
  ├── 点击"交易流水"
  │     └── AdminCookieTransactionsView
  │           ├── 高级筛选（用户/类型/时间/金额）
  │           ├── 汇总统计（收入/支出）
  │           └── 导出 CSV
  │
  └── 点击"定价策略"
        └── AdminCookiePricingView
              ├── 定价列表（任务类型/资源类型/单价）
              ├── 状态开关（生效/停用）
              ├── 新增/编辑定价
              └── 实时影响任务提交的费用预估
```

---

*文档生成完毕 — CygnusX 🥫 Cookie System Frontend v1.0*


---



---

# 12.3 饼干系统 — 与主框架融合方案

# CygnusX 🥫 饼干积分系统 — 主框架融合方案

> **版本**: v1.0
> **作者**: 系统集成架构师
> **日期**: 2025-01-20
> **状态**: 设计定稿

---

## 📋 目录

- [1. 系统架构总览](#1-系统架构总览)
- [2. 最小侵入集成策略](#2-最小侵入集成策略)
- [3. 集成点清单与代码实现](#3-集成点清单与代码实现)
- [4. 数据库迁移脚本](#4-数据库迁移脚本)
- [5. 部署配置更新](#5-部署配置更新)
- [6. 管理员操作接口](#6-管理员操作接口)
- [7. AI Agent 集成](#7-ai-agent-集成)
- [8. 向后兼容性保障](#8-向后兼容性保障)
- [9. 关键设计决策](#9-关键设计决策)
- [10. 异常处理与边界情况](#10-异常处理与边界情况)
- [11. 监控与告警](#11-监控与告警)

---

## 1. 系统架构总览

### 1.1 融合后架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CygnusX Platform                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │   Vue3      │  │  AI Copilot │  │  Admin      │  │   Cookie 💰      │    │
│  │   Frontend  │  │  (右侧边栏)  │  │  Dashboard  │  │   Dashboard     │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘    │
│         │                │                │                   │             │
│         └────────────────┴────────────────┴───────────────────┘             │
│                                     │                                        │
│                              FastAPI Backend                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │   │
│  │   │ Auth     │  │ Task     │  │ Sandbox  │  │ Cookie   │           │   │
│  │   │ Module   │  │ Module   │  │ Module   │  │ Module   │           │   │
│  │   │ (已有)   │  │ (已有)   │  │ (已有)   │  │ (新增)   │           │   │
│  │   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │   │
│  │        │             │             │             │                    │   │
│  │        └─────────────┴──────┬──────┴─────────────┘                    │   │
│  │                             │                                         │   │
│  │                      ┌──────┴──────┐                                  │   │
│  │                      │  Cookie     │                                  │   │
│  │                      │  Service    │                                  │   │
│  │                      │  (核心服务)  │                                  │   │
│  │                      └──────┬──────┘                                  │   │
│  │                             │                                         │   │
│  │   ┌────────────────────────┼────────────────────────┐                │   │
│  │   │                        │                        │                │   │
│  │   ▼                        ▼                        ▼                │   │
│  │  PostgreSQL            Redis                    Celery               │   │
│  │  ┌────────┐          ┌────────┐              ┌────────┐            │   │
│  │  │users   │          │cookie  │              │ task   │            │   │
│  │  │tasks   │          │balance │              │ queue  │            │   │
│  │  │sandbox │          │cache   │              │        │            │   │
│  │  │cookie_*│          │lock    │              │ celery │            │   │
│  │  └────────┘          │beat    │              │ beat   │            │   │
│  │                      └────────┘              └────────┘            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 饼干模块在代码库中的位置

```
cygnus-x/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── auth.py              # 已有 - 认证
│   │   │   ├── tasks.py             # 已有 - 任务 (需注入Cookie检查)
│   │   │   ├── sandbox.py           # 已有 - 沙盒 (需注入Cookie检查)
│   │   │   ├── admin/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── cookies.py       # 新增 - 管理员饼干管理
│   │   │   │   └── pricing.py       # 新增 - 定价策略管理
│   │   │   └── copilot/
│   │   │       └── tools.py         # 已有 - Agent工具 (需新增Cookie工具)
│   │   └── deps.py                  # 更新 - 依赖注入
│   ├── core/
│   │   └── config.py                # 更新 - 新增ENABLE_COOKIE_SYSTEM配置
│   ├── models/
│   │   ├── user.py                  # 已有 - 不变
│   │   ├── task.py                  # 已有 - 不变
│   │   └── cookie/
│   │       ├── __init__.py
│   │       ├── account.py           # 新增 - Cookie账户模型
│   │       ├── transaction.py       # 新增 - 交易流水模型
│   │       ├── pricing.py           # 新增 - 定价策略模型
│   │       └── consumption.py       # 新增 - 消费明细模型
│   ├── schemas/
│   │   └── cookie/
│   │       ├── __init__.py
│   │       ├── account.py           # 新增 - Pydantic Schema
│   │       ├── transaction.py       # 新增 - Pydantic Schema
│   │       ├── pricing.py           # 新增 - Pydantic Schema
│   │       └── consumption.py       # 新增 - Pydantic Schema
│   ├── services/
│   │   ├── auth_service.py          # 已有 - 不变
│   │   ├── task_service.py          # 已有 - 不变
│   │   ├── sandbox_service.py       # 已有 - 不变
│   │   └── cookie/
│   │       ├── __init__.py
│   │       ├── cookie_service.py    # 新增 - 核心服务类
│   │       ├── pricing_service.py   # 新增 - 定价服务
│   │       └── settlement_service.py # 新增 - 结算服务
│   ├── db/
│   │   └── triggers.py              # 新增 - 数据库触发器定义
│   └── celery/
│       └── tasks.py                 # 更新 - 任务回调中集成结算
├── migrations/
│   └── V008__add_cookie_system.sql  # 新增 - 数据库迁移
├── scripts/
│   └── init_cookies.py              # 新增 - 初始化脚本
└── docker-compose.yml               # 更新 - 环境变量
```

### 1.3 核心交互流程

```
用户注册 ──────────────────────────────────────────────────────────▶
    │                                                              │
    ▼                                                              │
[Trigger] 自动创建 cookie_accounts 记录                              │
    │  赠送 INITIAL_COOKIE_BALANCE (默认100🥫)                       │
    ▼                                                              │
用户提交任务 ───────────────────────────────────────────────────▶   │
    │                                                           │   │
    ▼                                                           │   │
[Task API] 调用 cookie_service.estimate_task_cost()             │   │
    │  根据 flow_category + resources 计算预估费用                 │   │
    ▼                                                           │   │
[Task API] 调用 cookie_service.check_balance()                  │   │
    │  检查余额是否充足                                            │   │
    ▼ ──余额不足──▶ 返回 402 Payment Required                    │   │
    │              提示充值                                        │   │
    ▼ ──余额充足──▶                                             │   │
[Task API] 调用 cookie_service.pre_deduct()                     │   │
    │  预扣预估费用，创建冻结记录                                   │   │
    │  使用 SELECT FOR UPDATE 悲观锁                               │   │
    ▼                                                           │   │
[Task API] 提交任务到 Celery Queue                              │   │
    │                                                           │   │
    ▼                                                           │   │
[Celery Worker] 执行任务 ◄──────────────────────────────────────┘   │
    │                                                               │
    ▼ ──任务完成──▶                                               │
[Celery Callback] 调用 cookie_service.settle()                     │
    │  多退少补：actual_cost < estimated → 退还差额                 │
    │           actual_cost > estimated → 补扣差额（检查余额）        │
    ▼ ──任务取消──▶                                               │
[Celery/API] 调用 cookie_service.refund()                         │
    │  全额退还预扣费用                                              │
    ▼                                                               │
  完成 ◄───────────────────────────────────────────────────────────┘


沙盒启动 ──────────────────────────────────────────────────────────▶
    │                                                              │
    ▼                                                              │
[Sandbox API] 调用 cookie_service.check_balance()                  │
    │  检查基础启动费用                                             │
    ▼ ──余额不足──▶ 返回 402，拒绝启动                             │
    ▼ ──余额充足──▶                                                │
[Sandbox API] 调用 cookie_service.pre_deduct(base_cost)            │
    │  预扣基础费用                                                 │
    ▼                                                              │
[Sandbox API] 启动Docker容器                                       │
    │                                                              │
    ▼                                                              │
[Celery Beat - 每分钟] 调用 cookie_service.charge_running_sandbox() │
    │  按运行时长扣费                                               │
    │  余额不足 → 标记即将终止，通知用户                             │
    │  余额耗尽 → 自动停止沙盒                                      │
    ▼                                                              │
[Sandbox API] 用户主动停止 / 自动停止                               │
    │                                                              │
    ▼                                                              │
[Sandbox API] 调用 cookie_service.settle_sandbox()                 │
    │  结算最终费用，多退少补                                        │
    ▼                                                              │
  完成 ◄───────────────────────────────────────────────────────────┘
```

---

## 2. 最小侵入集成策略

### 2.1 核心原则

| 原则 | 描述 | 实现方式 |
|------|------|----------|
| **零修改已有表** | 不改动 `users`、`tasks`、`sandbox_sessions` 表结构 | 通过外键关联 `cookie_*` 表 |
| **已有API兼容** | 所有已有接口的 URL、请求参数、响应格式不变 | 使用依赖注入和中间件在入口点拦截 |
| **功能可开关** | 饼干系统可通过环境变量一键禁用 | `ENABLE_COOKIE_SYSTEM=false` 时跳过所有检查 |
| **渐进式启用** | 已有用户自动迁移，新用户自动创建账户 | 数据库迁移脚本处理存量数据 |
| **异常降级** | Cookie 服务故障不影响核心业务 | try-catch 包裹，失败时允许操作继续 |

### 2.2 侵入点分析

```
侵入等级评估：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 高侵入（需修改已有代码文件）
   ├── app/api/v1/tasks.py         — 在 submit_task() 开头注入 Cookie 检查
   ├── app/api/v1/sandbox.py       — 在 start_sandbox() 开头注入 Cookie 检查
   ├── app/celery/tasks.py         — 在任务完成回调中注入结算逻辑
   ├── app/api/deps.py             — 新增 get_cookie_service() 依赖
   └── app/core/config.py          — 新增饼干相关配置项

🟡 中侵入（新增文件，已有代码引用）
   ├── app/services/cookie/        — 新增 Cookie 服务模块
   ├── app/models/cookie/          — 新增 Cookie 数据模型
   └── app/schemas/cookie/         — 新增 Pydantic Schema

🟢 低侵入（纯新增，不影响已有代码）
   ├── app/api/v1/admin/cookies.py — 新增管理员接口
   ├── migrations/V008*.sql        — 数据库迁移脚本
   └── scripts/init_cookies.py     — 初始化脚本
```

### 2.3 开关机制

```python
# app/core/config.py
class Settings(BaseSettings):
    # ... 已有配置 ...
    
    # ─── 饼干系统开关 ───
    ENABLE_COOKIE_SYSTEM: bool = True
    """总开关：禁用后所有饼干检查逻辑跳过"""
    
    INITIAL_COOKIE_BALANCE: Decimal = Decimal("100.00")
    """新用户初始饼干赠送数量"""
    
    COOKIE_SANDBOX_BASE_COST: Decimal = Decimal("5.00")
    """沙盒基础启动费用（🥫）"""
    
    COOKIE_SANDBOX_PER_MINUTE_COST: Decimal = Decimal("0.50")
    """沙盒每分钟运行费用（🥫）"""
    
    COOKIE_DEDUCTION_TIMEOUT_SECONDS: int = 300
    """预扣费用超时时间（秒），超时自动退还"""


# app/services/cookie/__init__.py
from app.core.config import settings
from functools import wraps

def cookie_required(func):
    """装饰器：当饼干系统禁用时直接跳过"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if not settings.ENABLE_COOKIE_SYSTEM:
            # 返回一个模拟的成功结果
            return CookieCheckResult(skipped=True, success=True)
        return await func(*args, **kwargs)
    return wrapper


# 使用示例：在TaskService中
class TaskService:
    @cookie_required
    async def submit_with_cookie_check(self, ...):
        # Cookie检查逻辑
        ...
```

---

## 3. 集成点清单与代码实现

### 3.1 集成点总表

| # | 集成点 | 已有模块 | 饼干系统介入方式 | 侵入等级 | 优先级 |
|---|--------|----------|------------------|----------|--------|
| 1 | 用户注册 | `users` 表 INSERT 触发器 | 自动创建 `cookie_accounts` 记录，赠送初始饼干 | 🟢 低 | P0 |
| 2 | 任务提交 | `POST /api/v1/tasks` | 提交前检查余额，预扣费用 | 🔴 高 | P0 |
| 3 | 任务完成 | Celery 任务完成回调 | 根据实际执行时长多退少补 | 🔴 高 | P0 |
| 4 | 任务取消 | `DELETE /api/v1/tasks/{id}/cancel` | 退还预扣饼干 | 🟡 中 | P1 |
| 5 | 沙盒启动 | `SandboxOrchestrator.start()` | 启动前检查余额，预扣基础费用 | 🔴 高 | P0 |
| 6 | 沙盒关闭 | `SandboxOrchestrator.stop()` | 结算最终费用 | 🟡 中 | P0 |
| 7 | 沙盒定时计费 | Celery Beat 定时任务 | 按分钟扣费，余额不足自动停止 | 🟡 中 | P1 |
| 8 | AI Agent 调度 | Copilot Agent 工具调用 | Agent 提交任务前检查余额 | 🟡 中 | P1 |
| 9 | 管理员调整 | 新增 `POST /admin/cookies/adjust` | 管理员手动调整用户余额 | 🟢 低 | P1 |
| 10 | 系统统计 | 新增 `GET /admin/cookies/stats` | 管理员查看饼干统计仪表盘 | 🟢 低 | P2 |

---

### 3.2 集成点 #1：用户注册自动创建饼干账户

**实现方式**：PostgreSQL 触发器 + 初始化脚本

```sql
-- migrations/V008__add_cookie_system.sql (部分)
-- 用户注册触发器

CREATE OR REPLACE FUNCTION create_cookie_account_on_user_insert()
RETURNS TRIGGER AS $$
DECLARE
    initial_balance DECIMAL(12,2);
BEGIN
    -- 获取初始赠送金额（默认100）
    initial_balance := COALESCE(
        (SELECT value::DECIMAL FROM system_settings WHERE key = 'initial_cookie_balance'),
        100.00
    );
    
    INSERT INTO cookie_accounts (
        user_id,
        balance,
        total_earned,
        total_consumed,
        status,
        created_at,
        updated_at
    ) VALUES (
        NEW.id,
        initial_balance,
        initial_balance,  -- 初始金额计入 earned
        0.00,
        'active',
        NOW(),
        NOW()
    );
    
    -- 记录初始赠送交易
    INSERT INTO cookie_transactions (
        user_id,
        type,
        amount,
        balance_after,
        source_type,
        source_id,
        description,
        created_at
    ) VALUES (
        NEW.id,
        'credit',
        initial_balance,
        initial_balance,
        'system',
        NEW.id,
        '新用户注册赠送初始饼干 🎉',
        NOW()
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 绑定触发器
CREATE TRIGGER trigger_create_cookie_account
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION create_cookie_account_on_user_insert();
```

---

### 3.3 集成点 #2：任务提交 — Cookie 检查与预扣

**目标文件**：`app/api/v1/tasks.py`

```python
# ═══════════════════════════════════════════════════════════
# app/api/v1/tasks.py — 任务提交接口（集成饼干系统）
# ═══════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_user, get_task_service, get_cookie_service
from app.services.cookie.cookie_service import CookieService
from app.services.task_service import TaskService
from app.schemas.task import TaskCreateRequest, TaskResponse
from app.core.config import settings
from decimal import Decimal

router = APIRouter()


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    req: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
    cookie_service: CookieService = Depends(get_cookie_service),
) -> TaskResponse:
    """
    提交分析任务（集成饼干系统）
    
    流程：
    1. 预估费用 → 2. 检查余额 → 3. 预扣费用 → 4. 提交任务
    """
    
    # ─── Step 0: 管理员绕过检查 ───
    if current_user.role == "admin" and settings.ADMIN_SKIP_COOKIE_CHECK:
        task = await task_service.submit_task(req, current_user.id)
        return task
    
    # ─── Step 1: 预估费用 ───
    estimated_cost: Decimal = await cookie_service.estimate_task_cost(
        flow_category=req.flow_category,
        resources=req.resources,
    )
    
    # ─── Step 2: 检查余额 ───
    current_balance: Decimal = await cookie_service.get_balance(current_user.id)
    
    if current_balance < estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "COOKIE_INSUFFICIENT",
                "message": "🥫 饼干余额不足，请先充值",
                "current_balance": float(current_balance),
                "required": float(estimated_cost),
                "shortage": float(estimated_cost - current_balance),
                "recharge_url": "/api/v1/cookies/recharge",
                "help": "联系管理员获取更多饼干",
            },
        )
    
    # ─── Step 3: 预扣费用 ───
    # 注意：预扣操作在数据库层使用 SELECT FOR UPDATE 保证原子性
    deduction_txn = await cookie_service.pre_deduct(
        user_id=current_user.id,
        amount=estimated_cost,
        source_type="task",
        source_id=None,  # 任务尚未创建，后续回填
        description=f"预扣任务费用: {req.name} (流程: {req.flow_category})",
        hold_expires_in_seconds=settings.COOKIE_DEDUCTION_TIMEOUT_SECONDS,
    )
    
    try:
        # ─── Step 4: 提交任务（原有逻辑不变）───
        task = await task_service.submit_task(req, current_user.id)
        
        # 回填任务ID到预扣记录
        await cookie_service.link_hold_to_task(
            hold_txn_id=deduction_txn.id,
            task_id=task.id,
        )
        
        # 将预估费用附加到任务记录（用于后续结算）
        await cookie_service.attach_task_metadata(
            task_id=task.id,
            estimated_cost=estimated_cost,
            hold_txn_id=deduction_txn.id,
        )
        
        return task
        
    except Exception as e:
        # 任务提交失败，退还预扣费用
        await cookie_service.refund_hold(
            hold_txn_id=deduction_txn.id,
            reason=f"任务提交失败: {str(e)}"
        )
        raise
```

---

### 3.4 集成点 #3：任务完成 — 多退少补结算

**目标文件**：`app/celery/tasks.py`

```python
# ═══════════════════════════════════════════════════════════
# app/celery/tasks.py — Celery 任务回调（集成饼干结算）
# ═══════════════════════════════════════════════════════════

from celery import Celery, chain
from app.services.cookie.settlement_service import SettlementService
from app.services.cookie.cookie_service import CookieService
from app.core.config import settings
from datetime import datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)
app = Celery("cygnusx")


@app.task(bind=True, max_retries=3)
def on_task_completed(self, task_id: str, task_result: dict):
    """
    任务完成回调 — 执行饼干费用结算
    
    结算逻辑：
    - actual < estimated: 退还差额
    - actual > estimated: 尝试补扣差额（余额不足则记录欠费）
    - actual = estimated: 无需操作，预扣转正
    """
    
    # 如果饼干系统禁用，跳过结算
    if not settings.ENABLE_COOKIE_SYSTEM:
        logger.info(f"[Cookie] 系统已禁用，跳过任务 {task_id} 的结算")
        return
    
    try:
        settlement_service = SettlementService()
        cookie_service = CookieService()
        
        # 获取任务元数据
        task_meta = cookie_service.get_task_metadata(task_id)
        if not task_meta:
            logger.warning(f"[Cookie] 任务 {task_id} 无饼干元数据，跳过结算")
            return
        
        hold_txn_id = task_meta["hold_txn_id"]
        estimated_cost = Decimal(str(task_meta["estimated_cost"]))
        
        # ─── 计算实际费用 ───
        started_at = task_result.get("started_at")
        completed_at = task_result.get("completed_at")
        resources = task_result.get("resources", {})
        
        actual_cost = cookie_service.calculate_actual_cost(
            flow_category=task_result.get("flow_category"),
            started_at=datetime.fromisoformat(started_at) if started_at else None,
            completed_at=datetime.fromisoformat(completed_at) if completed_at else datetime.utcnow(),
            resources=resources,
        )
        
        # ─── 执行结算 ───
        settlement_result = settlement_service.settle_task(
            task_id=task_id,
            user_id=task_result["user_id"],
            hold_txn_id=hold_txn_id,
            estimated=estimated_cost,
            actual=actual_cost,
        )
        
        logger.info(
            f"[Cookie] 任务 {task_id} 结算完成: "
            f"预估={estimated_cost}, 实际={actual_cost}, "
            f"调整={settlement_result['adjustment_amount']}"
        )
        
        return {
            "task_id": task_id,
            "estimated": float(estimated_cost),
            "actual": float(actual_cost),
            "adjustment": float(settlement_result["adjustment_amount"]),
            "status": "settled",
        }
        
    except Exception as exc:
        logger.error(f"[Cookie] 任务 {task_id} 结算失败: {exc}")
        # Celery 自动重试
        raise self.retry(exc=exc, countdown=60)


@app.task
def on_task_failed(task_id: str, task_result: dict, failure_reason: str):
    """
    任务失败回调 — 全额退还预扣饼干
    """
    if not settings.ENABLE_COOKIE_SYSTEM:
        return
    
    try:
        settlement_service = SettlementService()
        cookie_service = CookieService()
        
        task_meta = cookie_service.get_task_metadata(task_id)
        if not task_meta:
            return
        
        # 全额退款
        settlement_service.refund_task(
            task_id=task_id,
            user_id=task_result["user_id"],
            hold_txn_id=task_meta["hold_txn_id"],
            reason=f"任务执行失败: {failure_reason}",
        )
        
        logger.info(f"[Cookie] 任务 {task_id} 失败，已全额退还预扣饼干")
        
    except Exception as exc:
        logger.error(f"[Cookie] 任务 {task_id} 退款失败: {exc}")
        raise


@app.task
def on_task_cancelled(task_id: str, user_id: int):
    """
    任务取消回调 — 退还预扣饼干
    """
    if not settings.ENABLE_COOKIE_SYSTEM:
        return
    
    try:
        settlement_service = SettlementService()
        cookie_service = CookieService()
        
        task_meta = cookie_service.get_task_metadata(task_id)
        if not task_meta:
            return
        
        # 根据任务状态决定退款比例
        task_status = cookie_service.get_task_status(task_id)
        
        if task_status in ["pending", "queued"]:
            # 尚未执行，全额退还
            refund_ratio = Decimal("1.0")
        elif task_status == "running":
            # 执行中取消，按比例退还（已执行部分按实际费用结算）
            refund_ratio = Decimal("0.5")  # 简化处理，实际可按执行比例
        else:
            # 已完成或已失败，不退
            return
        
        settlement_service.partial_refund(
            task_id=task_id,
            user_id=user_id,
            hold_txn_id=task_meta["hold_txn_id"],
            refund_ratio=refund_ratio,
            reason=f"任务取消 ({task_status})",
        )
        
    except Exception as exc:
        logger.error(f"[Cookie] 任务 {task_id} 取消退款失败: {exc}")
        raise
```

---

### 3.5 集成点 #4：任务取消 — 退还预扣饼干

**目标文件**：`app/api/v1/tasks.py`（补充）

```python
# ═══════════════════════════════════════════════════════════
# app/api/v1/tasks.py — 任务取消接口（集成饼干退款）
# ═══════════════════════════════════════════════════════════

@router.delete("/tasks/{task_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    取消任务并退还预扣饼干
    """
    # 1. 取消任务（原有逻辑）
    task = await task_service.cancel_task(task_id, current_user.id)
    
    # 2. 饼干退款（如果系统启用）
    if settings.ENABLE_COOKIE_SYSTEM:
        try:
            # 触发异步退款（通过 Celery 确保原子性）
            from app.celery.tasks import on_task_cancelled
            on_task_cancelled.delay(task_id, current_user.id)
            
        except Exception as e:
            # 退款失败不影响取消操作，记录日志待人工处理
            logger.error(f"[Cookie] 任务 {task_id} 退款触发失败: {e}")
    
    return {
        "task_id": task_id,
        "status": "cancelled",
        "refund_processing": settings.ENABLE_COOKIE_SYSTEM,
    }
```

---

### 3.6 集成点 #5：沙盒启动 — Cookie 检查与预扣

**目标文件**：`app/sandbox/orchestrator.py`

```python
# ═══════════════════════════════════════════════════════════
# app/sandbox/orchestrator.py — 沙盒编排器（集成饼干系统）
# ═══════════════════════════════════════════════════════════

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.services.cookie.cookie_service import CookieService
from app.core.config import settings
from decimal import Decimal
import structlog

logger = structlog.get_logger(__name__)


class SandboxOrchestrator:
    """
    沙盒编排器 — 管理 Docker 沙盒的生命周期
    集成饼干积分系统进行费用管理
    """
    
    def __init__(self):
        self._containers: Dict[str, Dict] = {}  # session_id -> 容器信息
        self.cookie_service = CookieService()
        self.pricing = CookiePricing()  # 定价策略
    
    async def start_sandbox(
        self,
        user_id: int,
        project_id: str,
        image: str = "cygnusx/sandbox:latest",
        resources: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        启动沙盒（集成饼干检查）
        
        流程：
        1. 检查用户余额
        2. 预扣基础启动费
        3. 创建并启动 Docker 容器
        4. 注册到定时计费系统
        """
        
        # ─── 管理员绕过 ───
        user = await self._get_user(user_id)
        if user.role == "admin" and settings.ADMIN_SKIP_COOKIE_CHECK:
            logger.info(f"[Sandbox] 管理员 {user_id} 启动沙盒，绕过饼干检查")
            return await self._create_and_start(user_id, project_id, image, resources)
        
        # ─── Step 1: 检查余额 ───
        base_cost = self.pricing.get_sandbox_base_cost()
        min_required = base_cost + self.pricing.get_sandbox_min_reserve()
        
        current_balance = await self.cookie_service.get_balance(user_id)
        
        if current_balance < min_required:
            raise SandboxError(
                f"🥫 饼干余额不足。"
                f"需要至少 {float(min_required)} 🥫（含启动费 {float(base_cost)} + 预留 {float(self.pricing.get_sandbox_min_reserve())}），"
                f"当前余额: {float(current_balance)} 🥫",
                error_code="COOKIE_INSUFFICIENT",
                current_balance=float(current_balance),
                required=float(min_required),
                shortage=float(min_required - current_balance),
            )
        
        # ─── Step 2: 预扣基础启动费 ───
        try:
            hold_txn = await self.cookie_service.pre_deduct(
                user_id=user_id,
                amount=base_cost,
                source_type="sandbox",
                source_id=None,
                description=f"沙盒启动费用 (项目: {project_id})",
            )
        except InsufficientBalanceError:
            raise SandboxError(
                "🥫 余额不足，无法启动沙盒",
                error_code="COOKIE_HOLD_FAILED",
            )
        
        # ─── Step 3: 启动沙盒（原有逻辑）───
        try:
            sandbox = await self._create_and_start(
                user_id=user_id,
                project_id=project_id,
                image=image,
                resources=resources,
            )
            
            # 回填沙盒ID
            await self.cookie_service.link_hold_to_sandbox(
                hold_txn_id=hold_txn.id,
                session_id=sandbox["session_id"],
            )
            
            # 注册到内存计费表
            self._containers[sandbox["session_id"]] = {
                "user_id": user_id,
                "project_id": project_id,
                "started_at": datetime.utcnow(),
                "hold_txn_id": hold_txn.id,
                "last_billed_at": datetime.utcnow(),
                "total_billed": Decimal("0"),
                "status": "running",
                "resources": resources or {},
            }
            
            logger.info(
                f"[Sandbox] 沙盒 {sandbox['session_id']} 启动成功，"
                f"用户 {user_id} 预扣 {float(base_cost)} 🥫"
            )
            
            return sandbox
            
        except Exception as e:
            # 启动失败，退还预扣费用
            await self.cookie_service.refund_hold(
                hold_txn_id=hold_txn.id,
                reason=f"沙盒启动失败: {str(e)}"
            )
            raise SandboxError(f"沙盒启动失败，已退还预扣费用: {str(e)}")
    
    async def stop_sandbox(self, session_id: str, user_id: int) -> Dict[str, Any]:
        """
        停止沙盒并结算费用
        """
        container_info = self._containers.get(session_id)
        
        # ─── Step 1: 停止容器（原有逻辑）───
        result = await self._stop_and_remove(session_id)
        
        # ─── Step 2: 结算饼干费用 ───
        if settings.ENABLE_COOKIE_SYSTEM and container_info:
            try:
                runtime_seconds = (datetime.utcnow() - container_info["started_at"]).total_seconds()
                runtime_minutes = max(1, int(runtime_seconds / 60))
                
                # 计算实际费用（基础费 + 时长费）
                base_cost = self.pricing.get_sandbox_base_cost()
                per_minute_cost = self.pricing.get_sandbox_per_minute_cost()
                actual_cost = base_cost + (per_minute_cost * runtime_minutes)
                
                # 结算（多退少补）
                settlement = await self.cookie_service.settle_sandbox(
                    user_id=user_id,
                    session_id=session_id,
                    hold_txn_id=container_info["hold_txn_id"],
                    base_cost=base_cost,
                    actual_runtime_minutes=runtime_minutes,
                    actual_total_cost=actual_cost,
                )
                
                result["cookie_settlement"] = {
                    "runtime_minutes": runtime_minutes,
                    "actual_cost": float(actual_cost),
                    "refunded": float(settlement.get("refund_amount", 0)),
                    "extra_charged": float(settlement.get("extra_charge", 0)),
                }
                
                logger.info(
                    f"[Sandbox] 沙盒 {session_id} 停止，"
                    f"运行 {runtime_minutes} 分钟，"
                    f"实际费用 {float(actual_cost)} 🥫"
                )
                
            except Exception as e:
                logger.error(f"[Sandbox] 沙盒 {session_id} 结算失败: {e}")
                result["cookie_settlement_error"] = str(e)
        
        # 清理内存记录
        self._containers.pop(session_id, None)
        
        return result
    
    async def _create_and_start(self, user_id, project_id, image, resources):
        """原有容器创建逻辑（不变）"""
        ...
    
    async def _stop_and_remove(self, session_id):
        """原有容器停止逻辑（不变）"""
        ...


class SandboxError(Exception):
    """沙盒错误（扩展以支持额外字段）"""
    
    def __init__(self, message, error_code=None, **kwargs):
        super().__init__(message)
        self.error_code = error_code
        self.details = kwargs
```

---

### 3.7 集成点 #6 & #7：沙盒定时计费

**目标文件**：`app/celery/beat_schedule.py`（新增） + `app/celery/tasks.py`（补充）

```python
# ═══════════════════════════════════════════════════════════
# app/celery/beat_schedule.py — Celery Beat 定时任务配置
# ═══════════════════════════════════════════════════════════

from celery.schedules import crontab
from app.core.config import settings

beat_schedule = {
    # ... 已有定时任务 ...
    
    # ─── 沙盒定时计费 ───
    "sandbox-minute-billing": {
        "task": "app.celery.tasks.charge_running_sandboxes",
        "schedule": 60.0,  # 每60秒执行一次
        "options": {"queue": "billing"},
    },
    
    # ─── 预扣费用超时自动退还 ───
    "hold-expiry-refund": {
        "task": "app.celery.tasks.refund_expired_holds",
        "schedule": 300.0,  # 每5分钟检查一次
        "options": {"queue": "billing"},
    },
    
    # ─── 每日饼干统计 ───
    "daily-cookie-stats": {
        "task": "app.celery.tasks.generate_daily_cookie_report",
        "schedule": crontab(hour=0, minute=5),  # 每天凌晨 00:05
        "options": {"queue": "reports"},
    },
}


# ═══════════════════════════════════════════════════════════
# app/celery/tasks.py — 定时计费任务
# ═══════════════════════════════════════════════════════════

@app.task(bind=True, max_retries=3)
def charge_running_sandboxes(self):
    """
    每分钟对运行中的沙盒进行扣费
    
    逻辑：
    1. 查询所有 running 状态的沙盒会话
    2. 按分钟扣费
    3. 余额不足 → 标记即将终止 → 倒计时5分钟后强制停止
    4. 余额耗尽 → 立即强制停止
    """
    if not settings.ENABLE_COOKIE_SYSTEM:
        return {"processed": 0, "reason": "cookie_system_disabled"}
    
    try:
        cookie_service = CookieService()
        orchestrator = SandboxOrchestrator()
        
        results = {
            "processed": 0,
            "charged": 0,
            "failed": 0,
            "terminated": 0,
            "warned": 0,
        }
        
        # 获取所有运行中的沙盒
        running_sandboxes = orchestrator.get_running_sandboxes()
        
        for sandbox in running_sandboxes:
            session_id = sandbox["session_id"]
            user_id = sandbox["user_id"]
            
            try:
                # 计算本分钟费用
                per_minute_cost = CookiePricing().get_sandbox_per_minute_cost()
                
                # 执行扣费
                charge_result = cookie_service.charge_minute_fee(
                    user_id=user_id,
                    session_id=session_id,
                    amount=per_minute_cost,
                )
                
                if charge_result["success"]:
                    results["charged"] += 1
                elif charge_result["status"] == "insufficient":
                    # 余额不足
                    if charge_result.get("grace_period"):
                        # 还在宽限期内，发送警告
                        orchestrator.warn_sandbox_termination(session_id)
                        results["warned"] += 1
                    else:
                        # 宽限期已过，强制停止
                        orchestrator.force_stop_sandbox(session_id)
                        results["terminated"] += 1
                
                results["processed"] += 1
                
            except Exception as e:
                logger.error(f"[Sandbox Billing] 沙盒 {session_id} 计费失败: {e}")
                results["failed"] += 1
        
        return results
        
    except Exception as exc:
        logger.error(f"[Sandbox Billing] 定时计费任务失败: {exc}")
        raise self.retry(exc=exc, countdown=30)


@app.task
def refund_expired_holds():
    """
    退还超时的预扣费用
    防止因任务卡死或系统故障导致饼干被永久冻结
    """
    if not settings.ENABLE_COOKIE_SYSTEM:
        return
    
    cookie_service = CookieService()
    
    # 查找超时的预扣记录
    expired_holds = cookie_service.get_expired_holds(
        timeout_seconds=settings.COOKIE_DEDUCTION_TIMEOUT_SECONDS
    )
    
    refunded_count = 0
    for hold in expired_holds:
        try:
            cookie_service.refund_hold(
                hold_txn_id=hold["id"],
                reason="预扣超时自动退还",
            )
            refunded_count += 1
            logger.info(f"[Cookie] 预扣 {hold['id']} 超时已自动退还 {hold['amount']} 🥫")
        except Exception as e:
            logger.error(f"[Cookie] 预扣 {hold['id']} 退还失败: {e}")
    
    return {"refunded_count": refunded_count}


@app.task
def generate_daily_cookie_report():
    """
    生成每日饼干统计报告
    """
    if not settings.ENABLE_COOKIE_SYSTEM:
        return
    
    cookie_service = CookieService()
    report = cookie_service.generate_daily_report()
    
    # 发送给管理员（通过邮件/通知）
    # ...
    
    logger.info(f"[Cookie] 每日统计: 消费={report['total_consumed']}, 充值={report['total_earned']}")
    
    return report
```

---

### 3.8 集成点 #8：AI Agent 集成

**目标文件**：`app/api/v1/copilot/tools.py`（新增工具）

```python
# ═══════════════════════════════════════════════════════════
# app/api/v1/copilot/tools.py — AI Agent Cookie 工具
# ═══════════════════════════════════════════════════════════

from app.services.cookie.cookie_service import CookieService
from app.services.cookie.pricing_service import PricingService
from decimal import Decimal
from typing import Dict, Any


# ─── Agent 工具定义 ───

cookie_tools = [
    {
        "type": "function",
        "function": {
            "name": "check_cookie_balance",
            "description": "检查当前用户的饼干余额。当用户要执行任务或使用沙盒时，先调用此工具确认余额充足。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_task_cookies",
            "description": (
                "预估执行特定分析任务所需的饼干数量。"
                "在用户提交任务前调用，告知用户预估费用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "flow_category": {
                        "type": "string",
                        "enum": ["rna-seq", "chip-seq", "atac-seq", "variant-calling", "metagenomics", "single-cell", "custom"],
                        "description": "分析流程类型",
                    },
                    "cores": {
                        "type": "integer",
                        "description": "请求的CPU核数（默认4）",
                        "default": 4,
                    },
                    "memory_gb": {
                        "type": "integer",
                        "description": "请求的内存大小GB（默认16）",
                        "default": 16,
                    },
                    "estimated_hours": {
                        "type": "number",
                        "description": "预估执行时长（小时）",
                    },
                    "dataset_size_gb": {
                        "type": "number",
                        "description": "输入数据大小（GB）",
                    },
                },
                "required": ["flow_category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_sandbox_cookies",
            "description": (
                "预估启动沙盒会话所需的饼干数量。"
                "包括基础启动费和按预估使用时长的费用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "estimated_hours": {
                        "type": "number",
                        "description": "预估使用时长（小时）",
                        "default": 1,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pricing_info",
            "description": "获取当前的饼干定价策略信息，可用于向用户展示价目表。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ─── 工具实现 ───

class CookieAgentTools:
    """
    AI Agent 饼干工具实现
    被 Agent 执行器调用
    """
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.cookie_service = CookieService()
        self.pricing_service = PricingService()
    
    async def check_cookie_balance(self) -> Dict[str, Any]:
        """检查当前用户饼干余额"""
        balance = await self.cookie_service.get_balance(self.user_id)
        account_info = await self.cookie_service.get_account_info(self.user_id)
        
        return {
            "balance": float(balance),
            "unit": "🥫",
            "status": account_info["status"],
            "total_earned": float(account_info["total_earned"]),
            "total_consumed": float(account_info["total_consumed"]),
            "is_admin": account_info.get("is_admin", False),
        }
    
    async def estimate_task_cookies(
        self,
        flow_category: str,
        cores: int = 4,
        memory_gb: int = 16,
        estimated_hours: float = None,
        dataset_size_gb: float = None,
    ) -> Dict[str, Any]:
        """预估任务所需饼干"""
        
        resources = {
            "cores": cores,
            "memory_gb": memory_gb,
            "estimated_hours": estimated_hours,
            "dataset_size_gb": dataset_size_gb,
        }
        
        estimated_cost = await self.cookie_service.estimate_task_cost(
            flow_category=flow_category,
            resources=resources,
        )
        
        # 获取定价明细
        pricing_breakdown = self.pricing_service.get_task_pricing_breakdown(
            flow_category=flow_category,
            resources=resources,
        )
        
        return {
            "estimated_cost": float(estimated_cost),
            "unit": "🥫",
            "range": {
                "min": float(estimated_cost * Decimal("0.7")),
                "max": float(estimated_cost * Decimal("1.5")),
            },
            "breakdown": pricing_breakdown,
            "note": "实际费用可能因执行时长等因素上下浮动",
        }
    
    async def estimate_sandbox_cookies(self, estimated_hours: float = 1.0) -> Dict[str, Any]:
        """预估沙盒所需饼干"""
        
        base_cost = self.pricing_service.get_sandbox_base_cost()
        per_minute = self.pricing_service.get_sandbox_per_minute_cost()
        
        estimated_minutes = int(estimated_hours * 60)
        total_cost = base_cost + (per_minute * estimated_minutes)
        
        return {
            "estimated_cost": float(total_cost),
            "unit": "🥫",
            "breakdown": {
                "base_cost": float(base_cost),
                "runtime_cost": float(per_minute * estimated_minutes),
                "per_minute_rate": float(per_minute),
            },
            "note": f"预估使用 {estimated_hours} 小时，按每分钟 {float(per_minute)} 🥫 计费",
        }
    
    async def get_pricing_info(self) -> Dict[str, Any]:
        """获取定价信息"""
        return self.pricing_service.get_full_pricing_table()


# ═══════════════════════════════════════════════════════════
# Agent 对话示例（在系统提示词中配置）
# ═══════════════════════════════════════════════════════════

AGENT_COOKIE_PROMPT = """
你在协助用户使用 CygnusX 平台时，需要遵循以下饼干积分规则：

1. 当用户要求提交任务或启动沙盒时，必须先检查余额是否充足
2. 使用 check_cookie_balance 工具获取当前余额
3. 使用 estimate_task_cookies 或 estimate_sandbox_cookies 预估费用
4. 如果余额不足，告知用户需要充值（联系管理员）
5. 如果余额充足，向用户确认费用后再执行操作

对话示例：

用户: "帮我做一个RNA-seq分析"
Agent: [调用 estimate_task_cookies] → 预估需要 150-200 🥫
Agent: [调用 check_cookie_balance] → 当前余额 500 🥫
Agent: "RNA-seq 分析预估需要 150-200 🥫（范围：105-300），您当前有 500 🥫，余额充足。是否确认提交？"
用户: "确认"
Agent: [调用 submit_task] → 任务已提交

用户: "启动一个沙盒"
Agent: [调用 check_cookie_balance] → 当前余额 5 🥫
Agent: [调用 estimate_sandbox_cookies] → 预估需要 35 🥫（基础费5 + 1小时30）
Agent: "沙盒启动预估需要 35 🥫，但您当前只有 5 🥫，还差 30 🥫。请联系管理员充值后再试。"
"""
```

---

### 3.9 集成点 #9 & #10：管理员接口

详见 [第6节：管理员操作接口](#6-管理员操作接口)

---

## 4. 数据库迁移脚本

### 4.1 完整迁移脚本

```sql
-- ═══════════════════════════════════════════════════════════════════
-- Migration: V008__add_cookie_system.sql
-- Description: 饼干积分系统完整迁移
-- Author: System Architect
-- Date: 2025-01-20
-- ═══════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────
-- 1. 创建饼干账户表
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cookie_accounts (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 余额（DECIMAL 避免浮点精度问题）
    balance         DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    
    -- 统计字段（冗余设计，避免频繁聚合查询）
    total_earned    DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    total_consumed  DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    
    -- 账户状态
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'frozen', 'suspended', 'closed')),
    
    -- 时间戳
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT uq_cookie_accounts_user_id UNIQUE (user_id),
    CONSTRAINT ck_cookie_accounts_balance CHECK (balance >= 0)
);

COMMENT ON TABLE cookie_accounts IS '饼干账户表 — 每个用户一个账户';
COMMENT ON COLUMN cookie_accounts.balance IS '当前可用余额（🥫）';
COMMENT ON COLUMN cookie_accounts.status IS 'active=正常, frozen=冻结(只进不出), suspended=暂停(不进不出), closed=已关闭';


-- ─────────────────────────────────────────────────────────────────
-- 2. 创建交易流水表
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cookie_transactions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES cookie_accounts(id) ON DELETE CASCADE,
    
    -- 交易类型
    type            VARCHAR(20) NOT NULL
                    CHECK (type IN (
                        'credit',       -- 充值/收入
                        'debit',        -- 消费/支出
                        'pre_deduct',   -- 预扣（冻结）
                        'refund',       -- 退款
                        'settle',       -- 结算（多退少补）
                        'adjust',       -- 管理员调整
                        'bonus',        -- 奖励
                        'penalty'       -- 惩罚
                    )),
    
    -- 金额（正数）
    amount          DECIMAL(12, 2) NOT NULL,
    
    -- 交易后余额（快照）
    balance_after   DECIMAL(12, 2) NOT NULL,
    
    -- 关联业务
    source_type     VARCHAR(30) NOT NULL
                    CHECK (source_type IN ('task', 'sandbox', 'system', 'admin', 'manual', 'bonus')),
    source_id       VARCHAR(100),  -- 关联的业务ID（任务ID、沙盒会话ID等）
    
    -- 描述
    description     TEXT NOT NULL,
    
    -- 管理员操作记录（当 type='adjust' 时填写）
    admin_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    admin_reason    TEXT,  -- 管理员操作原因
    
    -- 关联的预扣交易（用于结算/退款追溯）
    hold_txn_id     BIGINT REFERENCES cookie_transactions(id) ON DELETE SET NULL,
    
    -- 预扣超时时间（仅 pre_deduct 类型使用）
    hold_expires_at TIMESTAMP WITH TIME ZONE,
    
    -- 交易状态
    status          VARCHAR(20) NOT NULL DEFAULT 'completed'
                    CHECK (status IN ('pending', 'completed', 'cancelled', 'expired')),
    
    -- 时间戳
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP WITH TIME ZONE,  -- 完成时间（预扣→结算时更新）
    
    -- 索引
    CONSTRAINT uq_hold_txn_per_source 
        UNIQUE NULLS NOT DISTINCT (source_type, source_id, status) 
        WHERE type = 'pre_deduct' AND status = 'pending'
);

COMMENT ON TABLE cookie_transactions IS '饼干交易流水表 — 不可删除，仅追加';
COMMENT ON COLUMN cookie_transactions.type IS 'credit=充值, debit=消费, pre_deduct=预扣冻结, refund=退款, settle=结算, adjust=管理员调整, bonus=奖励, penalty=惩罚';
COMMENT ON COLUMN cookie_transactions.source_type IS 'task=任务, sandbox=沙盒, system=系统, admin=管理员操作, manual=手动, bonus=奖励';
COMMENT ON COLUMN cookie_transactions.hold_txn_id IS '指向触发此交易的预扣记录（用于结算和退款追溯）';


-- ─────────────────────────────────────────────────────────────────
-- 3. 创建定价策略表
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cookie_pricing (
    id              SERIAL PRIMARY KEY,
    
    -- 定价项标识
    item_code       VARCHAR(50) NOT NULL UNIQUE,
    item_name       VARCHAR(100) NOT NULL,
    category        VARCHAR(30) NOT NULL
                    CHECK (category IN ('task', 'sandbox', 'storage', 'feature')),
    
    -- 计费方式
    pricing_type    VARCHAR(20) NOT NULL
                    CHECK (pricing_type IN ('fixed', 'per_hour', 'per_minute', 'per_gb', 'tiered')),
    
    -- 基础价格
    base_price      DECIMAL(12, 4) NOT NULL DEFAULT 0.0000,
    
    -- 阶梯/单位价格（JSON格式，灵活配置）
    tier_config     JSONB DEFAULT NULL,
    -- tier_config 示例:
    -- {"tier1": {"max": 10, "price": 1.0}, "tier2": {"max": 100, "price": 0.8}}
    
    -- 资源乘数（JSON格式）
    resource_multipliers JSONB DEFAULT '{}',
    -- resource_multipliers 示例:
    -- {"cores": 0.5, "memory_gb": 0.1, "gpu": 2.0}
    
    -- 适用条件
    flow_categories VARCHAR(50)[] DEFAULT NULL,  -- 适用的流程类型
    
    -- 生效时间
    effective_from  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMP WITH TIME ZONE,  -- NULL 表示一直有效
    
    -- 状态
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- 元数据
    description     TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    
    -- 时间戳
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE cookie_pricing IS '饼干定价策略表 — 支持动态定价';


-- ─────────────────────────────────────────────────────────────────
-- 4. 创建消费明细表（用于统计和审计）
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cookie_consumptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES cookie_accounts(id) ON DELETE CASCADE,
    
    -- 消费类型
    source_type     VARCHAR(30) NOT NULL,
    source_id       VARCHAR(100) NOT NULL,
    
    -- 费用明细
    base_cost       DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    resource_cost   DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    extra_cost      DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    total_cost      DECIMAL(12, 2) NOT NULL,
    
    -- 资源使用快照
    resources_used  JSONB DEFAULT '{}',
    -- resources_used 示例:
    -- {"cores": 8, "memory_gb": 32, "runtime_seconds": 3600, "dataset_size_gb": 5.2}
    
    -- 关联的定价策略
    pricing_id      INTEGER REFERENCES cookie_pricing(id) ON DELETE SET NULL,
    
    -- 关联的交易记录
    transaction_id  BIGINT NOT NULL REFERENCES cookie_transactions(id) ON DELETE CASCADE,
    
    -- 时间戳
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at        TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE cookie_consumptions IS '消费明细表 — 记录每次资源使用的详细费用构成';


-- ─────────────────────────────────────────────────────────────────
-- 5. 创建索引（性能优化）
-- ─────────────────────────────────────────────────────────────────

-- cookie_accounts 索引
CREATE INDEX idx_cookie_accounts_user_id ON cookie_accounts(user_id);
CREATE INDEX idx_cookie_accounts_status ON cookie_accounts(status) WHERE status != 'closed';

-- cookie_transactions 索引
CREATE INDEX idx_transactions_user_created ON cookie_transactions(user_id, created_at DESC);
CREATE INDEX idx_transactions_source ON cookie_transactions(source_type, source_id);
CREATE INDEX idx_transactions_type ON cookie_transactions(type, status);
CREATE INDEX idx_transactions_hold_expires ON cookie_transactions(hold_expires_at) 
    WHERE type = 'pre_deduct' AND status = 'pending';
CREATE INDEX idx_transactions_admin ON cookie_transactions(admin_id) WHERE admin_id IS NOT NULL;

-- cookie_pricing 索引
CREATE INDEX idx_pricing_active ON cookie_pricing(is_active, category) WHERE is_active = TRUE;

-- cookie_consumptions 索引
CREATE INDEX idx_consumptions_user_created ON cookie_consumptions(user_id, created_at DESC);
CREATE INDEX idx_consumptions_source ON cookie_consumptions(source_type, source_id);
CREATE INDEX idx_consumptions_transaction ON cookie_consumptions(transaction_id);


-- ─────────────────────────────────────────────────────────────────
-- 6. 为已有用户创建饼干账户（赠送初始饼干）
-- ─────────────────────────────────────────────────────────────────

DO $$
DECLARE
    initial_balance DECIMAL(12, 2) := 100.00;
    user_record RECORD;
    new_account_id INTEGER;
BEGIN
    FOR user_record IN SELECT id, username FROM users WHERE id NOT IN (
        SELECT user_id FROM cookie_accounts WHERE user_id IS NOT NULL
    )
    LOOP
        -- 创建账户
        INSERT INTO cookie_accounts (
            user_id, balance, total_earned, total_consumed, status, created_at, updated_at
        ) VALUES (
            user_record.id,
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN 999999.99 ELSE initial_balance END,  -- 管理员给无限饼干
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN 999999.99 ELSE initial_balance END,
            0.00,
            'active',
            NOW(),
            NOW()
        )
        RETURNING id INTO new_account_id;
        
        -- 创建初始交易记录
        INSERT INTO cookie_transactions (
            user_id, account_id, type, amount, balance_after,
            source_type, source_id, description, status, created_at, completed_at
        ) VALUES (
            user_record.id,
            new_account_id,
            'credit',
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN 999999.99 ELSE initial_balance END,
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN 999999.99 ELSE initial_balance END,
            'system',
            user_record.id::TEXT,
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN '管理员账户初始化（无限饼干）' ELSE '存量用户迁移赠送 🎁' END,
            'completed',
            NOW(),
            NOW()
        );
        
        RAISE NOTICE '已为用户 % (ID: %) 创建饼干账户，余额: %', 
            user_record.username, user_record.id,
            CASE WHEN EXISTS (
                SELECT 1 FROM users u WHERE u.id = user_record.id AND u.role = 'admin'
            ) THEN '∞ (admin)' ELSE initial_balance::TEXT END;
    END LOOP;
END $$;


-- ─────────────────────────────────────────────────────────────────
-- 7. 插入默认定价策略
-- ─────────────────────────────────────────────────────────────────

INSERT INTO cookie_pricing (
    item_code, item_name, category, pricing_type, base_price,
    resource_multipliers, flow_categories, description, is_active, effective_from
) VALUES 
-- 沙盒定价
('sandbox.base', '沙盒基础启动费', 'sandbox', 'fixed', 5.0000,
 '{}', NULL, '每次启动沙盒的基础费用', TRUE, NOW()),

('sandbox.per_minute', '沙盒运行时长费', 'sandbox', 'per_minute', 0.5000,
 '{}', NULL, '沙盒每分钟运行费用', TRUE, NOW()),

-- RNA-seq 流程定价
('task.rna-seq', 'RNA-seq 分析', 'task', 'tiered', 50.0000,
 '{"cores": 2.0, "memory_gb": 0.5, "per_hour": 10.0}',
 '{"rna-seq"}', 'RNA测序分析标准流程', TRUE, NOW()),

('task.chip-seq', 'ChIP-seq 分析', 'task', 'tiered', 60.0000,
 '{"cores": 2.0, "memory_gb": 0.5, "per_hour": 12.0}',
 '{"chip-seq"}', 'ChIP测序分析标准流程', TRUE, NOW()),

('task.atac-seq', 'ATAC-seq 分析', 'task', 'tiered', 55.0000,
 '{"cores": 2.0, "memory_gb": 0.5, "per_hour": 11.0}',
 '{"atac-seq"}', 'ATAC测序分析标准流程', TRUE, NOW()),

('task.variant', '变异检测分析', 'task', 'tiered', 80.0000,
 '{"cores": 2.5, "memory_gb": 0.8, "per_hour": 15.0}',
 '{"variant-calling"}', '变异检测与注释流程', TRUE, NOW()),

('task.metagenomics', '宏基因组分析', 'task', 'tiered', 70.0000,
 '{"cores": 2.0, "memory_gb": 0.6, "per_hour": 13.0}',
 '{"metagenomics"}', '宏基因组分析流程', TRUE, NOW()),

('task.single-cell', '单细胞分析', 'task', 'tiered', 100.0000,
 '{"cores": 3.0, "memory_gb": 1.0, "per_hour": 20.0}',
 '{"single-cell"}', '单细胞RNA测序分析流程', TRUE, NOW()),

('task.custom', '自定义流程', 'task', 'tiered', 40.0000,
 '{"cores": 1.5, "memory_gb": 0.3, "per_hour": 8.0}',
 '{"custom"}', '用户自定义Snakemake流程', TRUE, NOW())

ON CONFLICT (item_code) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────
-- 8. 创建触发器：用户注册时自动创建饼干账户
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION trg_create_cookie_account_for_new_user()
RETURNS TRIGGER AS $$
DECLARE
    initial_balance DECIMAL(12, 2);
    new_account_id INTEGER;
BEGIN
    -- 从系统设置获取初始余额（如不存在则用默认值）
    initial_balance := COALESCE(
        (SELECT (value)::DECIMAL FROM system_settings WHERE key = 'initial_cookie_balance' LIMIT 1),
        100.00
    );
    
    -- 创建饼干账户
    INSERT INTO cookie_accounts (
        user_id, balance, total_earned, total_consumed, 
        status, created_at, updated_at
    ) VALUES (
        NEW.id,
        initial_balance,
        initial_balance,
        0.00,
        'active',
        NOW(),
        NOW()
    )
    RETURNING id INTO new_account_id;
    
    -- 记录初始赠送交易
    INSERT INTO cookie_transactions (
        user_id, account_id, type, amount, balance_after,
        source_type, source_id, description, status,
        created_at, completed_at
    ) VALUES (
        NEW.id,
        new_account_id,
        'credit',
        initial_balance,
        initial_balance,
        'system',
        NEW.id::TEXT,
        '新用户注册赠送初始饼干 🎉',
        'completed',
        NOW(),
        NOW()
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 绑定触发器
DROP TRIGGER IF EXISTS trg_auto_cookie_account ON users;
CREATE TRIGGER trg_auto_cookie_account
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION trg_create_cookie_account_for_new_user();


-- ─────────────────────────────────────────────────────────────────
-- 9. 创建触发器：自动更新 updated_at 字段
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION trg_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cookie_accounts_updated_at
    BEFORE UPDATE ON cookie_accounts
    FOR EACH ROW
    EXECUTE FUNCTION trg_update_updated_at();

CREATE TRIGGER trg_cookie_pricing_updated_at
    BEFORE UPDATE ON cookie_pricing
    FOR EACH ROW
    EXECUTE FUNCTION trg_update_updated_at();


-- ─────────────────────────────────────────────────────────────────
-- 10. 创建视图：用户饼干账户完整信息
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_user_cookie_accounts AS
SELECT 
    u.id AS user_id,
    u.username,
    u.email,
    u.role,
    ca.id AS account_id,
    ca.balance,
    ca.total_earned,
    ca.total_consumed,
    ca.status AS account_status,
    CASE 
        WHEN u.role = 'admin' THEN TRUE 
        ELSE FALSE 
    END AS is_admin,
    CASE 
        WHEN u.role = 'admin' THEN NULL  -- 管理员无限制
        ELSE ca.balance 
    END AS effective_balance,
    ca.created_at AS account_created_at,
    ca.updated_at AS account_updated_at
FROM users u
LEFT JOIN cookie_accounts ca ON u.id = ca.user_id;

COMMENT ON VIEW v_user_cookie_accounts IS '用户饼干账户完整信息视图（含管理员无限标识）';


-- ─────────────────────────────────────────────────────────────────
-- 11. 创建视图：交易流水完整信息（含用户信息）
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_cookie_transactions_full AS
SELECT 
    ct.*,
    u.username AS user_username,
    u.email AS user_email,
    au.username AS admin_username,
    ca.balance AS current_balance
FROM cookie_transactions ct
JOIN users u ON ct.user_id = u.id
LEFT JOIN users au ON ct.admin_id = au.id
LEFT JOIN cookie_accounts ca ON ct.account_id = ca.id;

COMMENT ON VIEW v_cookie_transactions_full IS '交易流水完整视图（含用户和管理员信息）';


-- ─────────────────────────────────────────────────────────────────
-- 12. 创建视图：每日消费统计
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_daily_cookie_stats AS
SELECT 
    DATE(created_at) AS date,
    source_type,
    type,
    COUNT(*) AS transaction_count,
    SUM(amount) AS total_amount,
    COUNT(DISTINCT user_id) AS unique_users
FROM cookie_transactions
WHERE status = 'completed'
GROUP BY DATE(created_at), source_type, type
ORDER BY date DESC, source_type, type;


-- ─────────────────────────────────────────────────────────────────
-- 13. 验证迁移
-- ─────────────────────────────────────────────────────────────────

DO $$
DECLARE
    user_count INTEGER;
    account_count INTEGER;
    pricing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO user_count FROM users;
    SELECT COUNT(*) INTO account_count FROM cookie_accounts;
    SELECT COUNT(*) INTO pricing_count FROM cookie_pricing;
    
    RAISE NOTICE '═══════════════════════════════════════════════════════════════';
    RAISE NOTICE '  饼干积分系统迁移完成！';
    RAISE NOTICE '  总用户数: %', user_count;
    RAISE NOTICE '  已创建饼干账户: %', account_count;
    RAISE NOTICE '  定价策略数: %', pricing_count;
    RAISE NOTICE '═══════════════════════════════════════════════════════════════';
END $$;
```

### 4.2 回滚脚本

```sql
-- ═══════════════════════════════════════════════════════════════════
-- Rollback: V008__rollback_cookie_system.sql
-- Description: 饼干积分系统回滚（谨慎使用！）
-- ⚠️ 注意：回滚会删除所有饼干相关数据，不可恢复！
-- ═══════════════════════════════════════════════════════════════════

-- 删除触发器
DROP TRIGGER IF EXISTS trg_auto_cookie_account ON users;
DROP TRIGGER IF EXISTS trg_cookie_accounts_updated_at ON cookie_accounts;
DROP TRIGGER IF EXISTS trg_cookie_pricing_updated_at ON cookie_pricing;

-- 删除函数
DROP FUNCTION IF EXISTS trg_create_cookie_account_for_new_user();
DROP FUNCTION IF EXISTS trg_update_updated_at();

-- 删除视图
DROP VIEW IF EXISTS v_daily_cookie_stats;
DROP VIEW IF EXISTS v_cookie_transactions_full;
DROP VIEW IF EXISTS v_user_cookie_accounts;

-- 删除表（注意顺序：先删外键依赖的）
DROP TABLE IF EXISTS cookie_consumptions CASCADE;
DROP TABLE IF EXISTS cookie_transactions CASCADE;
DROP TABLE IF EXISTS cookie_pricing CASCADE;
DROP TABLE IF EXISTS cookie_accounts CASCADE;
```

---

## 5. 部署配置更新

### 5.1 docker-compose.yml 更新

```yaml
# ═══════════════════════════════════════════════════════════
# docker-compose.yml — 饼干系统集成更新
# ═══════════════════════════════════════════════════════════

services:
  # ... 已有服务（api, db, redis, celery-worker, celery-beat 等）...

  api:
    build: .
    environment:
      # ... 已有环境变量 ...
      
      # ─── 饼干系统配置 ───
      ENABLE_COOKIE_SYSTEM: "true"
      INITIAL_COOKIE_BALANCE: "100.00"
      COOKIE_SANDBOX_BASE_COST: "5.00"
      COOKIE_SANDBOX_PER_MINUTE_COST: "0.50"
      COOKIE_DEDUCTION_TIMEOUT_SECONDS: "300"
      ADMIN_SKIP_COOKIE_CHECK: "true"
      
      # 可选：外部计费系统接入（预留）
      EXTERNAL_BILLING_ENABLED: "false"
      EXTERNAL_BILLING_API_URL: ""
      EXTERNAL_BILLING_API_KEY: ""
    depends_on:
      - db
      - redis

  celery-worker:
    build: .
    command: celery -A app.celery worker -l info -Q default,billing,reports
    environment:
      # ... 已有环境变量 ...
      ENABLE_COOKIE_SYSTEM: "true"
    depends_on:
      - db
      - redis

  celery-beat:
    build: .
    command: celery -A app.celery beat -l info
    environment:
      # ... 已有环境变量 ...
      ENABLE_COOKIE_SYSTEM: "true"
    depends_on:
      - db
      - redis

  # 可选：Redis 已存在，无需新增服务
  # 饼干系统使用现有 Redis 实例进行：
  # - 余额缓存（减少数据库查询）
  # - 分布式锁（防止并发扣费）
  # - 实时计费状态
```

### 5.2 环境变量配置表

| 变量名 | 默认值 | 说明 | 必填 |
|--------|--------|------|------|
| `ENABLE_COOKIE_SYSTEM` | `true` | 饼干系统总开关 | 否 |
| `INITIAL_COOKIE_BALANCE` | `100.00` | 新用户初始饼干数量 | 否 |
| `COOKIE_SANDBOX_BASE_COST` | `5.00` | 沙盒基础启动费 | 否 |
| `COOKIE_SANDBOX_PER_MINUTE_COST` | `0.50` | 沙盒每分钟费用 | 否 |
| `COOKIE_DEDUCTION_TIMEOUT_SECONDS` | `300` | 预扣超时时间（秒） | 否 |
| `ADMIN_SKIP_COOKIE_CHECK` | `true` | 管理员跳过饼干检查 | 否 |
| `COOKIE_CACHE_TTL_SECONDS` | `60` | 余额缓存时间 | 否 |
| `COOKIE_LOCK_TIMEOUT_SECONDS` | `10` | 扣费分布式锁超时 | 否 |

### 5.3 init.sh 初始化脚本更新

```bash
#!/bin/bash
# ═══════════════════════════════════════════════════════════
# scripts/init.sh — 系统初始化脚本（集成饼干系统）
# ═══════════════════════════════════════════════════════════

set -e

echo "🚀 CygnusX 初始化开始..."

# ─── 1. 等待数据库就绪 ───
echo "⏳ 等待数据库就绪..."
until pg_isready -h db -p 5432 -U postgres; do
    sleep 1
done
echo "✅ 数据库已就绪"

# ─── 2. 运行数据库迁移 ───
echo "📦 运行数据库迁移..."
cd /app

# 运行 Flyway / Alembic / 或其他迁移工具
# 确保 V008__add_cookie_system.sql 被执行
if command -v flyway &> /dev/null; then
    flyway migrate
else
    # 使用 Python 执行迁移脚本
    python -c "
import asyncio
from app.db.session import engine
from pathlib import Path

async def run_migration():
    migration_file = Path('migrations/V008__add_cookie_system.sql')
    if migration_file.exists():
        print('执行饼干系统迁移...')
        with open(migration_file) as f:
            sql = f.read()
        async with engine.begin() as conn:
            await conn.execute(sql)
        print('✅ 迁移完成')
    else:
        print('⚠️ 迁移文件不存在，跳过')

asyncio.run(run_migration())
"
fi

# ─── 3. 初始化饼干系统数据 ───
echo "🥫 初始化饼干系统..."
python scripts/init_cookies.py

# ─── 4. 创建管理员账户（如果指定了ADMIN_USERNAME）───
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "👤 创建管理员账户..."
    python -c "
import asyncio
from app.services.auth_service import AuthService
from app.schemas.user import UserCreate

async def create_admin():
    auth_service = AuthService()
    try:
        user = await auth_service.create_user(
            UserCreate(
                username='$ADMIN_USERNAME',
                email='${ADMIN_USERNAME}@cygnusx.local',
                password='$ADMIN_PASSWORD',
                role='admin'
            )
        )
        print(f'✅ 管理员账户 {user.username} 已创建（拥有无限饼干）')
    except Exception as e:
        print(f'⚠️ 管理员账户创建失败（可能已存在）: {e}')

asyncio.run(create_admin())
"
fi

# ─── 5. 验证饼干系统 ───
echo "🔍 验证饼干系统..."
python -c "
import asyncio
from app.services.cookie.cookie_service import CookieService

async def verify():
    cookie_service = CookieService()
    
    # 检查定价策略是否已加载
    pricing = await cookie_service.get_pricing_table()
    print(f'定价策略: {len(pricing)} 项')
    
    # 检查已有用户是否都有饼干账户
    stats = await cookie_service.get_system_stats()
    print(f'饼干账户: {stats[\"total_accounts\"]} 个')
    print(f'总余额: {stats[\"total_balance\"]} 🥫')
    
    print('✅ 饼干系统验证通过')

asyncio.run(verify())
"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ CygnusX 初始化完成！"
echo "  🥫 饼干积分系统已就绪"
echo "═══════════════════════════════════════════════════"
```

### 5.4 初始化脚本 init_cookies.py

```python
#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════
# scripts/init_cookies.py — 饼干系统初始化
# ═══════════════════════════════════════════════════════════

import asyncio
import asyncpg
from decimal import Decimal
from app.core.config import settings


async def init_cookie_system():
    """
    饼干系统初始化：
    1. 为没有饼干账户的已有用户创建账户
    2. 验证定价策略已加载
    3. 检查系统配置
    """
    conn = await asyncpg.connect(settings.DATABASE_URL)
    
    try:
        print("🥫 开始初始化饼干系统...")
        
        # 1. 为已有用户创建饼干账户
        result = await conn.execute(
            """
            INSERT INTO cookie_accounts (user_id, balance, total_earned, total_consumed, status, created_at, updated_at)
            SELECT 
                u.id,
                CASE WHEN u.role = 'admin' THEN 999999.99 ELSE $1 END,
                CASE WHEN u.role = 'admin' THEN 999999.99 ELSE $1 END,
                0.00,
                'active',
                NOW(),
                NOW()
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM cookie_accounts ca WHERE ca.user_id = u.id
            )
            """,
            Decimal(settings.INITIAL_COOKIE_BALANCE)
        )
        print(f"  ✅ 为已有用户创建了饼干账户")
        
        # 2. 为上述用户创建初始交易记录
        await conn.execute(
            """
            INSERT INTO cookie_transactions (
                user_id, account_id, type, amount, balance_after,
                source_type, source_id, description, status, created_at, completed_at
            )
            SELECT 
                u.id,
                ca.id,
                'credit',
                CASE WHEN u.role = 'admin' THEN 999999.99 ELSE $1 END,
                CASE WHEN u.role = 'admin' THEN 999999.99 ELSE $1 END,
                'system',
                u.id::TEXT,
                CASE WHEN u.role = 'admin' 
                    THEN '管理员账户初始化（无限饼干）' 
                    ELSE '存量用户迁移赠送 🎁' 
                END,
                'completed',
                NOW(),
                NOW()
            FROM users u
            JOIN cookie_accounts ca ON u.id = ca.user_id
            WHERE NOT EXISTS (
                SELECT 1 FROM cookie_transactions ct 
                WHERE ct.user_id = u.id AND ct.source_type = 'system'
            )
            """,
            Decimal(settings.INITIAL_COOKIE_BALANCE)
        )
        print(f"  ✅ 初始交易记录已创建")
        
        # 3. 验证定价策略
        pricing_count = await conn.fetchval(
            "SELECT COUNT(*) FROM cookie_pricing WHERE is_active = TRUE"
        )
        if pricing_count == 0:
            print("  ⚠️ 警告：没有激活的定价策略，请检查迁移脚本")
        else:
            print(f"  ✅ 定价策略已加载: {pricing_count} 项")
        
        # 4. 统计信息
        stats = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) as total_accounts,
                COALESCE(SUM(balance), 0) as total_balance,
                COUNT(CASE WHEN balance > 999999 THEN 1 END) as admin_accounts
            FROM cookie_accounts
            """
        )
        print(f"  📊 当前饼干账户: {stats['total_accounts']} 个")
        print(f"  📊 总余额: {stats['total_balance']} 🥫")
        print(f"  📊 管理员账户: {stats['admin_accounts']} 个")
        
        print("✅ 饼干系统初始化完成！")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(init_cookie_system())
```

---

## 6. 管理员操作接口

### 6.1 完整管理员 API

```python
# ═══════════════════════════════════════════════════════════
# app/api/v1/admin/cookies.py — 管理员饼干管理 API
# ═══════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, date
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin, get_db, get_cookie_service
from app.services.cookie.cookie_service import CookieService
from app.services.cookie.pricing_service import PricingService
from app.models.user import User

router = APIRouter(prefix="/admin/cookies", tags=["admin-cookies"])


# ─── Pydantic Schemas ───

class CookieAdjustRequest(BaseModel):
    """管理员调整用户饼干余额请求"""
    user_id: int = Field(..., description="目标用户ID")
    amount: Decimal = Field(..., description="调整金额（正数=充值，负数=扣减）")
    reason: str = Field(..., min_length=1, max_length=500, description="调整原因")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 42,
                "amount": "500.00",
                "reason": "月度奖励发放"
            }
        }


class CookieAdjustResponse(BaseModel):
    """管理员调整响应"""
    transaction_id: int
    user_id: int
    username: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    type: str
    reason: str
    admin_id: int
    created_at: datetime


class CookieStatsQuery(BaseModel):
    """统计查询参数"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    group_by: Optional[str] = "day"  # day, week, month


class CookieStatsResponse(BaseModel):
    """饼干统计仪表盘响应"""
    period: dict  # {start, end}
    total_accounts: int
    active_accounts: int
    total_balance: Decimal
    total_consumed: Decimal
    total_earned: Decimal
    today_consumption: Decimal
    today_earned: Decimal
    active_accounts_today: int
    top_consumers: List[dict]
    consumption_by_category: dict
    consumption_trend: List[dict]
    recent_transactions: List[dict]


class PricingUpdateRequest(BaseModel):
    """定价策略更新请求"""
    base_price: Optional[Decimal] = None
    tier_config: Optional[dict] = None
    resource_multipliers: Optional[dict] = None
    is_active: Optional[bool] = None
    effective_until: Optional[datetime] = None


# ─── API 端点 ───

@router.post("/adjust", response_model=CookieAdjustResponse, status_code=status.HTTP_200_OK)
async def admin_adjust_cookies(
    req: CookieAdjustRequest,
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
    db: AsyncSession = Depends(get_db),
):
    """
    ## 管理员调整用户饼干余额
    
    权限：仅管理员
    
    - **amount > 0**: 为用户充值饼干
    - **amount < 0**: 从用户账户扣减饼干（不可扣至负数）
    - **必须填写 reason**: 用于审计
    
    操作会被完整记录到交易流水，包含操作人 admin_id
    """
    
    # 不能调整自己（避免误操作）
    if req.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能调整自己的饼干余额，请通过其他管理员操作"
        )
    
    try:
        result = await cookie_service.admin_adjust_balance(
            admin_id=current_user.id,
            user_id=req.user_id,
            amount=req.amount,
            reason=req.reason,
        )
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/stats", response_model=CookieStatsResponse)
async def admin_cookie_stats(
    start_date: Optional[date] = Query(None, description="统计开始日期"),
    end_date: Optional[date] = Query(None, description="统计结束日期"),
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 饼干统计仪表盘
    
    返回系统级别的饼干统计数据：
    - 账户总数与活跃数
    - 余额总量
    - 消费/收入趋势
    - Top 消费者排行
    - 分类消费统计
    """
    
    stats = await cookie_service.get_admin_stats(
        start_date=start_date,
        end_date=end_date,
    )
    
    return stats


@router.get("/users/{user_id}/account")
async def admin_get_user_account(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 查看指定用户的饼干账户详情
    
    包含：余额、交易历史、消费统计
    """
    account = await cookie_service.get_user_account_detail(user_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户饼干账户不存在"
        )
    return account


@router.get("/users/{user_id}/transactions")
async def admin_get_user_transactions(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[str] = Query(None, description="过滤交易类型"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 查看指定用户的交易流水
    
    支持分页和过滤
    """
    transactions = await cookie_service.get_user_transactions(
        user_id=user_id,
        page=page,
        page_size=page_size,
        txn_type=type,
        start_date=start_date,
        end_date=end_date,
    )
    return transactions


@router.post("/users/{user_id}/freeze")
async def admin_freeze_account(
    user_id: int,
    reason: str = Query(..., description="冻结原因"),
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 冻结用户饼干账户
    
    冻结后：用户无法消费（任务提交/沙盒启动会被拒绝），但可以接收充值
    """
    result = await cookie_service.freeze_account(
        admin_id=current_user.id,
        user_id=user_id,
        reason=reason,
    )
    return {"status": "frozen", "user_id": user_id, "reason": reason}


@router.post("/users/{user_id}/unfreeze")
async def admin_unfreeze_account(
    user_id: int,
    reason: str = Query(..., description="解冻原因"),
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 解冻用户饼干账户
    """
    result = await cookie_service.unfreeze_account(
        admin_id=current_user.id,
        user_id=user_id,
        reason=reason,
    )
    return {"status": "active", "user_id": user_id, "reason": reason}


# ═══════════════════════════════════════════════════════════
# 定价策略管理
# ═══════════════════════════════════════════════════════════

@router.get("/pricing")
async def admin_list_pricing(
    category: Optional[str] = Query(None),
    current_user: User = Depends(get_current_admin),
    pricing_service: PricingService = Depends(),
):
    """
    ## 列出所有定价策略
    """
    pricing = await pricing_service.list_pricing(category=category)
    return pricing


@router.put("/pricing/{item_code}")
async def admin_update_pricing(
    item_code: str,
    req: PricingUpdateRequest,
    current_user: User = Depends(get_current_admin),
    pricing_service: PricingService = Depends(),
):
    """
    ## 更新定价策略
    
    动态调整价格，无需重启服务
    """
    updated = await pricing_service.update_pricing(
        item_code=item_code,
        admin_id=current_user.id,
        **req.dict(exclude_unset=True),
    )
    return updated


@router.post("/pricing/batch-update")
async def admin_batch_update_pricing(
    updates: List[dict],
    current_user: User = Depends(get_current_admin),
    pricing_service: PricingService = Depends(),
):
    """
    ## 批量更新定价策略
    
    用于大规模调价场景
    """
    results = await pricing_service.batch_update_pricing(
        admin_id=current_user.id,
        updates=updates,
    )
    return {"updated": results}


@router.get("/pricing/history")
async def admin_pricing_history(
    item_code: Optional[str] = Query(None),
    current_user: User = Depends(get_current_admin),
    pricing_service: PricingService = Depends(),
):
    """
    ## 定价策略变更历史
    
    审计用途
    """
    history = await pricing_service.get_pricing_history(item_code=item_code)
    return history


# ═══════════════════════════════════════════════════════════
# 批量操作
# ═══════════════════════════════════════════════════════════

@router.post("/batch-recharge")
async def admin_batch_recharge(
    user_ids: List[int],
    amount: Decimal,
    reason: str,
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 批量充值
    
    给多个用户同时充值饼干
    """
    results = []
    for user_id in user_ids:
        try:
            result = await cookie_service.admin_adjust_balance(
                admin_id=current_user.id,
                user_id=user_id,
                amount=amount,
                reason=reason,
            )
            results.append({"user_id": user_id, "status": "success", **result})
        except Exception as e:
            results.append({"user_id": user_id, "status": "failed", "error": str(e)})
    
    return {
        "total": len(user_ids),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "details": results,
    }


@router.get("/export/transactions")
async def admin_export_transactions(
    start_date: date,
    end_date: date,
    format: str = Query("csv", enum=["csv", "json"]),
    current_user: User = Depends(get_current_admin),
    cookie_service: CookieService = Depends(get_cookie_service),
):
    """
    ## 导出交易流水
    
    用于财务审计和数据分析
    """
    data = await cookie_service.export_transactions(
        start_date=start_date,
        end_date=end_date,
        format=format,
    )
    return data
```

### 6.2 权限控制中间件

```python
# ═══════════════════════════════════════════════════════════
# app/api/deps.py — 依赖注入（更新）
# ═══════════════════════════════════════════════════════════

from fastapi import Depends, HTTPException, status
from app.services.cookie.cookie_service import CookieService
from app.models.user import User

async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    验证当前用户是管理员
    
    用于管理员专属接口的权限控制
    """
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此操作需要管理员权限",
        )
    return current_user


def get_cookie_service() -> CookieService:
    """CookieService 依赖注入工厂"""
    return CookieService()
```

---

## 7. AI Agent 集成

### 7.1 Agent 工具注册

```python
# ═══════════════════════════════════════════════════════════
# app/api/v1/copilot/agent.py — Agent 配置更新
# ═══════════════════════════════════════════════════════════

from app.api.v1.copilot.tools import cookie_tools, CookieAgentTools

# 在 Agent 初始化时注册 Cookie 工具
class CopilotAgent:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.tools = self._register_tools()
    
    def _register_tools(self):
        tools = [
            # ... 已有工具（submit_task, query_data, etc.）...
            
            # ─── 饼干工具 ───
            *cookie_tools,  # 展开 Cookie 工具定义
        ]
        return tools
    
    async def execute_tool(self, tool_name: str, params: dict):
        """执行工具调用"""
        
        cookie_tool_map = {
            "check_cookie_balance": CookieAgentTools(self.user_id).check_cookie_balance,
            "estimate_task_cookies": CookieAgentTools(self.user_id).estimate_task_cookies,
            "estimate_sandbox_cookies": CookieAgentTools(self.user_id).estimate_sandbox_cookies,
            "get_pricing_info": CookieAgentTools(self.user_id).get_pricing_info,
        }
        
        if tool_name in cookie_tool_map:
            return await cookie_tool_map[tool_name](**params)
        
        # ... 处理其他工具 ...
```

### 7.2 Agent 系统提示词（Cookie 相关部分）

```yaml
# ═══════════════════════════════════════════════════════════
# config/agent_system_prompt.yaml — Agent 系统提示词
# ═══════════════════════════════════════════════════════════

system_prompt: |
  你是 CygnusX 平台的 AI 助手，帮助用户进行生物信息学分析。
  
  ## 饼干积分规则
  
  平台使用 "饼干" (🥫) 作为积分货币。用户在提交任务和启动沙盒时需要消耗饼干。
  
  ### 操作要求
  
  1. **提交任务前**：必须调用 `estimate_task_cookies` 预估费用，再调用 `check_cookie_balance` 确认余额充足
  2. **启动沙盒前**：必须调用 `estimate_sandbox_cookies` 预估费用，再调用 `check_cookie_balance` 确认余额充足
  3. **余额不足时**：告知用户当前余额和所需金额，建议联系管理员充值
  4. **余额充足时**：向用户展示预估费用和余额，询问确认后再执行操作
  
  ### 对话示例
  
  **场景：用户提交 RNA-seq 任务**
  
  用户: "帮我做一个RNA-seq分析"
  → [调用 estimate_task_cookies, flow_category="rna-seq"]
  → [调用 check_cookie_balance]
  → Assistant: "RNA-seq 分析预估需要 150-200 🥫，您当前有 500 🥫，余额充足。是否确认提交？"
  用户: "确认"
  → [调用 submit_task]
  → Assistant: "✅ 任务已提交！任务ID: task_12345，预估消耗 150 🥫。"
  
  **场景：用户启动沙盒但余额不足**
  
  用户: "启动一个沙盒"
  → [调用 check_cookie_balance]
  → [调用 estimate_sandbox_cookies]
  → Assistant: "沙盒启动需要基础费 5 🥫 + 运行费（每分钟 0.5 🥫）。您当前只有 3 🥫，余额不足（至少需 10 🥫）。请联系管理员充值后再试。"
  
  ### 注意事项
  
  - 不要替用户做决定，必须获得明确确认后再消费饼干
  - 预估费用给出范围（min-max），告知用户实际费用可能浮动
  - 如果任务失败，饼干会自动退还，请告知用户无需担心
  - 管理员用户不受饼干限制（balance 会显示 is_admin=true）
```

### 7.3 Agent 执行流程图

```
用户输入 ──────────────────────────────────────────────────────────▶
    │                                                              │
    ▼                                                              │
[Agent] 解析意图                                                  │
    │                                                              │
    ├── 提交任务 ──────────▶                                      │
    │    │                  │                                     │
    │    ▼                  │                                     │
    │   [调用estimate_task_cookies]                              │
    │    │                  │                                     │
    │    ▼                  │                                     │
    │   [调用check_cookie_balance]                               │
    │    │                  │                                     │
    │    ├── 余额充足 ──────┤                                     │
    │    │    │             │                                     │
    │    │    ▼             │                                     │
    │    │   向用户确认费用  │                                     │
    │    │    │             │                                     │
    │    │    ├── 用户确认 ──┤                                     │
    │    │    │    │        │                                     │
    │    │    │    ▼        │                                     │
    │    │    │   [调用submit_task]  ───▶ 任务提交成功             │
    │    │    │                                                       │
    │    │    ├── 用户取消 ──▶ 取消操作                              │
    │    │                                                            │
    │    ├── 余额不足 ──────▶ 告知用户，建议充值                      │
    │                                                               │
    ├── 启动沙盒 ──────────▶                                        │
    │    │                  │                                       │
    │    ▼                  │                                       │
    │   [调用estimate_sandbox_cookies]                              │
    │    │                  │                                       │
    │    ▼                  │                                       │
    │   [调用check_cookie_balance]                                 │
    │    │                  │                                       │
    │    ├── 余额充足 ──────┤                                       │
    │    │    ▼             │                                       │
    │    │   向用户确认费用  │                                       │
    │    │    │             │                                       │
    │    │    ├── 确认 ──────┤                                       │
    │    │    │    ▼        │                                       │
    │    │    │   [调用start_sandbox] ──▶ 沙盒启动成功               │
    │    │    │                                                       │
    │    │    ├── 取消 ─────▶ 取消操作                               │
    │    │                                                            │
    │    └── 余额不足 ──────▶ 告知用户余额不足                       │
    │                                                               │
    └── 其他意图 ──────────▶ 正常处理                                │
                                                                   │
◄──────────────────────────────────────────────────────────────────┘
```

---

## 8. 向后兼容性保障

### 8.1 兼容性策略矩阵

| 场景 | 策略 | 实现方式 |
|------|------|----------|
| **已有用户的任务** | 自动迁移 | 迁移脚本为所有已有用户创建饼干账户并赠送初始饼干 |
| **正在执行的任务** | 免计费 | 迁移前已提交的任务不触发饼干检查 |
| **管理员操作** | 无限饼干 | 管理员 balance = 999999.99，API 检查 is_admin 标志 |
| **系统开关关闭** | 完全绕过 | `ENABLE_COOKIE_SYSTEM=false` 时所有检查逻辑短路返回 |
| **Cookie 服务故障** | 优雅降级 | try-catch 包裹，服务不可用时允许操作继续 |
| **API 版本兼容** | 响应格式不变 | 在原有响应中可选附加 cookie 字段，不破坏已有客户端 |

### 8.2 开关关闭时的行为

```python
# ═══════════════════════════════════════════════════════════
# app/services/cookie/compat.py — 兼容性层
# ═══════════════════════════════════════════════════════════

from app.core.config import settings
from functools import wraps
from typing import Optional

class CookieBypassResult:
    """饼干系统绕过时的模拟结果"""
    skipped = True
    success = True
    balance = 999999.99
    is_admin = False
    
    def __bool__(self):
        return True


def cookie_check_required(func):
    """
    装饰器：饼干检查的装饰器
    
    当 ENABLE_COOKIE_SYSTEM=false 时，直接返回成功
    当 Cookie 服务不可用时，记录日志但允许操作继续
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 1. 系统关闭，直接跳过
        if not settings.ENABLE_COOKIE_SYSTEM:
            return CookieBypassResult()
        
        # 2. 管理员绕过
        user_id = kwargs.get('user_id')
        if user_id and await _is_admin(user_id):
            result = CookieBypassResult()
            result.is_admin = True
            return result
        
        # 3. 正常执行
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # 4. 服务故障，优雅降级
            logger = kwargs.get('logger')
            if logger:
                logger.error(f"[Cookie] 服务异常，允许操作继续: {e}")
            else:
                import logging
                logging.getLogger(__name__).error(f"[Cookie] 服务异常，允许操作继续: {e}")
            
            # 返回一个警告性成功结果
            result = CookieBypassResult()
            result.degraded = True
            result.warning = "饼干服务暂时不可用，操作已允许继续"
            return result
    
    return wrapper


async def _is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    # 简化实现，实际应查询数据库
    from app.services.auth_service import AuthService
    auth_service = AuthService()
    user = await auth_service.get_user(user_id)
    return user and user.role in ["admin", "superadmin"]


# 使用示例
class TaskService:
    @cookie_check_required
    async def submit_task_with_check(self, user_id: int, ...):
        """提交任务（自动处理饼干检查和兼容性）"""
        ...
```

### 8.3 环境变量切换指南

```bash
# 完全启用饼干系统（生产环境）
ENABLE_COOKIE_SYSTEM=true
ADMIN_SKIP_COOKIE_CHECK=true
INITIAL_COOKIE_BALANCE=100.00

# 完全禁用饼干系统（兼容模式）
ENABLE_COOKIE_SYSTEM=false

# 仅管理员免计费（测试环境）
ENABLE_COOKIE_SYSTEM=true
ADMIN_SKIP_COOKIE_CHECK=true
INITIAL_COOKIE_BALANCE=999999.99  # 给普通用户也大量饼干

# 严格模式（所有用户都计费，包括管理员）
ENABLE_COOKIE_SYSTEM=true
ADMIN_SKIP_COOKIE_CHECK=false
```

---

## 9. 关键设计决策

### 9.1 决策记录（ADR）

| # | 决策点 | 选择 | 理由 | 替代方案 | 状态 |
|---|--------|------|------|----------|------|
| ADR-001 | 计费时机 | **预扣 + 结算** | 防止超支，保证系统稳定；用户感知清晰 | 后付费：可能导致坏账 | ✅ 已采纳 |
| ADR-002 | 余额字段类型 | **DECIMAL(12,2)** | 精确计算，避免浮点误差；支持小数精度 | FLOAT/DOUBLE：精度问题 | ✅ 已采纳 |
| ADR-003 | 并发控制 | **SELECT FOR UPDATE** | 悲观锁，数据库层面保证原子性；实现简单 | 乐观锁：需要版本字段，冲突处理复杂 | ✅ 已采纳 |
| ADR-004 | 管理员权限 | **无限饼干** | 管理员执行任务不受限制，便于系统维护 | 单独配额：增加复杂度 | ✅ 已采纳 |
| ADR-005 | 定价配置 | **数据库存储** | 管理员可动态调整，无需重启服务 | 配置文件：需要重启，不灵活 | ✅ 已采纳 |
| ADR-006 | 交易流水 | **不可删除** | 满足审计要求，保证数据完整性 | 可删除：审计风险 | ✅ 已采纳 |
| ADR-007 | 缓存策略 | **Redis 缓存 + DB 持久化** | 余额读多写少，缓存提升性能；定时同步 | 纯数据库：性能较差 | ✅ 已采纳 |
| ADR-008 | 分布式锁 | **Redis RedLock** | 防止并发扣费导致超支 | 数据库锁：性能差 | ✅ 已采纳 |
| ADR-009 | 系统开关 | **环境变量控制** | 一键启用/禁用，运维友好 | 数据库存储：需要查询，延迟 | ✅ 已采纳 |
| ADR-010 | 超时退款 | **自动退还机制** | 防止因任务卡死导致饼干永久冻结 | 手动退款：运维负担大 | ✅ 已采纳 |

### 9.2 技术选型对比

```
并发控制方案对比：
┌─────────────────┬───────────────────┬───────────────────┬───────────────────┐
│ 方案            │ 悲观锁            │ 乐观锁            │ 无锁（原子操作）   │
├─────────────────┼───────────────────┼───────────────────┼───────────────────┤
│ 实现复杂度      │ 低                │ 中                │ 高                │
│ 性能            │ 中（有锁等待）     │ 高（无锁等待）     │ 极高              │
│ 冲突处理        │ 自动排队          │ 需重试逻辑         │ 无需处理          │
│ 超支风险        │ 无                │ 低（重试足够时）    │ 有（ABA问题）     │
│ 适用场景        │ 本方案            │ 读多写少          │ 高频极简操作      │
└─────────────────┴───────────────────┴───────────────────┴───────────────────┘

选择：悲观锁（SELECT FOR UPDATE）
理由：饼干扣费是资金操作，安全性 > 性能；冲突频率不高
```

---

## 10. 异常处理与边界情况

### 10.1 异常场景处理表

| 场景 | 处理方式 | 用户感知 | 补偿机制 |
|------|----------|----------|----------|
| 预扣后任务提交失败 | 自动全额退款 | "任务提交失败，已退还饼干" | Celery 定时任务兜底 |
| 任务执行超时 | 按实际执行时间结算 | 无（后台处理） | 超时退款任务 |
| 沙盒强制停止（余额耗尽） | 停止容器 + 最终结算 | "沙盒因余额不足已自动停止" | 保留最近5分钟数据 |
| 并发扣费冲突 | 第二个请求等待或失败 | "操作繁忙，请稍后重试" | 自动重试3次 |
| Cookie 服务不可用 | 优雅降级，允许操作 | 无（静默处理） | 日志告警 |
| 定价策略不存在 | 使用默认定价 | 无 | 管理员通知 |
| 负数金额调整 | 拒绝操作 | "金额不能为负数" | — |
| 扣减超过余额 | 拒绝操作 | "余额不足" | — |
| 管理员扣减管理员 | 拒绝操作 | "不能调整管理员的余额" | — |
| 数据库事务失败 | 回滚所有操作 | "系统繁忙，请稍后重试" | 自动重试 |

### 10.2 核心服务异常处理代码

```python
# ═══════════════════════════════════════════════════════════
# app/services/cookie/exceptions.py — 异常定义
# ═══════════════════════════════════════════════════════════

class CookieException(Exception):
    """饼干系统基础异常"""
    pass


class InsufficientBalanceError(CookieException):
    """余额不足"""
    def __init__(self, current_balance: Decimal, required: Decimal):
        self.current_balance = current_balance
        self.required = required
        super().__init__(
            f"余额不足: 当前 {current_balance} 🥫, 需要 {required} 🥫, "
            f"差 {required - current_balance} 🥫"
        )


class HoldExpiredError(CookieException):
    """预扣已过期"""
    pass


class AccountFrozenError(CookieException):
    """账户已冻结"""
    pass


class PricingNotFoundError(CookieException):
    """定价策略不存在"""
    pass


class ConcurrentOperationError(CookieException):
    """并发操作冲突"""
    pass


class SettlementError(CookieException):
    """结算异常"""
    pass
```

---

## 11. 监控与告警

### 11.1 关键监控指标

```python
# ═══════════════════════════════════════════════════════════
# app/services/cookie/metrics.py — 监控指标
# ═══════════════════════════════════════════════════════════

from prometheus_client import Counter, Histogram, Gauge, Info

# 交易计数器
cookie_transactions_total = Counter(
    'cookie_transactions_total',
    'Total cookie transactions',
    ['type', 'source_type', 'status']
)

# 余额分布
cookie_balance_gauge = Gauge(
    'cookie_account_balance',
    'Current cookie balance per user',
    ['user_id']
)

# 消费耗时
cookie_operation_duration = Histogram(
    'cookie_operation_duration_seconds',
    'Cookie operation duration',
    ['operation'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

# 系统总览
cookie_system_info = Info(
    'cookie_system',
    'Cookie system information'
)

# 错误计数器
cookie_errors_total = Counter(
    'cookie_errors_total',
    'Total cookie system errors',
    ['error_type']
)

# 活跃沙盒计费
cookie_sandbox_active_gauge = Gauge(
    'cookie_sandbox_active_count',
    'Number of active sandboxes being billed'
)
```

### 11.2 告警规则

```yaml
# ═══════════════════════════════════════════════════════════
# monitoring/cookie_alerts.yml — 告警规则
# ═══════════════════════════════════════════════════════════

groups:
  - name: cookie_system_alerts
    rules:
      # 余额不足用户过多
      - alert: CookieLowBalanceUsers
        expr: |
          count(cookie_account_balance < 10) > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "大量用户饼干余额不足"
          description: "超过 50 个用户余额低于 10 🥫"

      # 交易异常增多
      - alert: CookieTransactionErrors
        expr: |
          rate(cookie_errors_total[5m]) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "饼干系统错误率过高"
          description: "每分钟错误数超过 5"

      # 预扣超时未退还
      - alert: CookieExpiredHoldsPending
        expr: |
          cookie_expired_holds_count > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "存在大量超时未退还的预扣"
          description: "超过 10 笔预扣超时未处理"

      # 余额为负（数据异常）
      - alert: CookieNegativeBalance
        expr: |
          cookie_account_balance < 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "发现负余额账户"
          description: "用户 {{ $labels.user_id }} 余额为负"
```

---

## 附录 A：完整接口清单

### A.1 用户接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/cookies/balance` | 查询当前余额 | ✅ JWT |
| GET | `/api/v1/cookies/transactions` | 查询交易流水 | ✅ JWT |
| GET | `/api/v1/cookies/pricing` | 查询定价表 | ✅ JWT |

### A.2 管理员接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/admin/cookies/adjust` | 调整用户余额 | ✅ Admin |
| GET | `/api/v1/admin/cookies/stats` | 统计仪表盘 | ✅ Admin |
| GET | `/api/v1/admin/cookies/users/{id}/account` | 用户账户详情 | ✅ Admin |
| GET | `/api/v1/admin/cookies/users/{id}/transactions` | 用户交易流水 | ✅ Admin |
| POST | `/api/v1/admin/cookies/users/{id}/freeze` | 冻结账户 | ✅ Admin |
| POST | `/api/v1/admin/cookies/users/{id}/unfreeze` | 解冻账户 | ✅ Admin |
| GET | `/api/v1/admin/cookies/pricing` | 定价策略列表 | ✅ Admin |
| PUT | `/api/v1/admin/cookies/pricing/{code}` | 更新定价 | ✅ Admin |
| POST | `/api/v1/admin/cookies/batch-recharge` | 批量充值 | ✅ Admin |
| GET | `/api/v1/admin/cookies/export/transactions` | 导出交易 | ✅ Admin |

### A.3 Agent 工具

| 工具名 | 说明 |
|--------|------|
| `check_cookie_balance` | 检查余额 |
| `estimate_task_cookies` | 预估任务费用 |
| `estimate_sandbox_cookies` | 预估沙盒费用 |
| `get_pricing_info` | 获取定价信息 |

---

## 附录 B：术语表

| 术语 | 说明 |
|------|------|
| 🥫 饼干 | CygnusX 平台积分货币单位 |
| 预扣 (Hold) | 在操作前冻结一部分余额，操作完成后结算 |
| 结算 (Settle) | 根据实际消耗，将预扣金额转为正式消费或退还差额 |
| 多退少补 | 实际费用 < 预扣 → 退还差额；实际费用 > 预扣 → 补扣差额 |
| 悲观锁 | 数据库 SELECT FOR UPDATE，操作期间锁定记录 |
| 优雅降级 | 服务故障时，不影响核心业务流程 |

---

> **文档结束** — 本方案覆盖 CygnusX 饼干积分系统与主框架的全部集成点，确保最小侵入、向后兼容、可开关控制。


---

