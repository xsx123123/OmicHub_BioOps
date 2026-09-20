"""任务域值对象"""

from enum import Enum


class TaskStatus(str, Enum):
    """任务状态机"""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    """执行模式"""

    LOCAL = "local"
    REMOTE = "remote"


class LogLevel(str, Enum):
    """日志级别"""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# 合法的状态转换
# 终态不可重开（WP2 任务4）：success/failed/cancelled 一经写入即不可再迁移，
# 与 OpenAI4S compute/states.py 的终态语义一致——终态证据（结果/原因/时间戳）
# 只允许写一次，迟到的探测或重试不得复活已结束的任务；需要再次执行时
# 必须提交新任务（新 job 行 + 新幂等键）。
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCESS: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}
