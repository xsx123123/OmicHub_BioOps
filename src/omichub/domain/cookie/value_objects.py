"""饼干域值对象 — 枚举与类型定义"""

from enum import Enum


class TransactionType(str, Enum):
    """交易类型"""

    EARN = "earn"
    SPEND = "spend"
    ADJUST = "adjust"
    REFUND = "refund"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"


class AccountStatus(str, Enum):
    """账户状态"""

    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"


class PricingType(str, Enum):
    """定价类型"""

    TASK_TYPE = "task_type"
    RESOURCE = "resource"
    SANDBOX = "sandbox"
    BONUS = "bonus"


class PricingUnit(str, Enum):
    """计价单位"""

    PER_TASK = "per_task"
    PER_HOUR = "per_hour"
    PER_CORE_HOUR = "per_core_hour"
    PER_GB_HOUR = "per_gb_hour"
    PER_SESSION = "per_session"
    PER_USER = "per_user"
    PER_SAMPLE = "per_sample"
    PER_COMPARISON = "per_comparison"


class BillingItem(str, Enum):
    """消费明细项"""

    TASK_BASE = "task_base"
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    EXECUTION_TIME = "execution_time"
    SANDBOX_SESSION = "sandbox_session"
    SANDBOX_CPU = "sandbox_cpu"
    SANDBOX_MEMORY = "sandbox_memory"
