"""沙盒域值对象"""

from enum import Enum


class SandboxStatus(str, Enum):
    """沙盒会话状态"""

    CREATING = "creating"
    READY = "ready"
    EXECUTING = "executing"
    IDLE = "idle"
    PAUSED = "paused"
    ERROR = "error"
    DESTROYED = "destroyed"


class ExecutionStatus(str, Enum):
    """代码执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
