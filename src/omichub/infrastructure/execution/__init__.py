"""工作流执行器"""

from omichub.infrastructure.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionResult,
)
from omichub.infrastructure.execution.binary import BinaryExecutor
from omichub.infrastructure.execution.local import LocalSnakemakeExecutor
from omichub.infrastructure.execution.registry import get_executor, register_executor

__all__ = [
    "BaseExecutor",
    "ExecutionContext",
    "ExecutionResult",
    "BinaryExecutor",
    "LocalSnakemakeExecutor",
    "get_executor",
    "register_executor",
]
