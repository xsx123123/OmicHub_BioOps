# OmicHub 🥫 饼干积分系统 — 主框架融合方案

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
│                              OmicHub Platform                                │
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
omic-hub/
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
app = Celery("omichub")


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
        image: str = "omichub/sandbox:latest",
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
你在协助用户使用 OmicHub 平台时，需要遵循以下饼干积分规则：

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

echo "🚀 OmicHub 初始化开始..."

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
                email='${ADMIN_USERNAME}@omichub.local',
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
echo "  ✅ OmicHub 初始化完成！"
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
  你是 OmicHub 平台的 AI 助手，帮助用户进行生物信息学分析。
  
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
| 🥫 饼干 | OmicHub 平台积分货币单位 |
| 预扣 (Hold) | 在操作前冻结一部分余额，操作完成后结算 |
| 结算 (Settle) | 根据实际消耗，将预扣金额转为正式消费或退还差额 |
| 多退少补 | 实际费用 < 预扣 → 退还差额；实际费用 > 预扣 → 补扣差额 |
| 悲观锁 | 数据库 SELECT FOR UPDATE，操作期间锁定记录 |
| 优雅降级 | 服务故障时，不影响核心业务流程 |

---

> **文档结束** — 本方案覆盖 OmicHub 饼干积分系统与主框架的全部集成点，确保最小侵入、向后兼容、可开关控制。
