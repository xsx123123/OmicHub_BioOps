"""工作流执行器"""

from cygnusx.infrastructure.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionResult,
)
from cygnusx.infrastructure.execution.binary import BinaryExecutor
from cygnusx.infrastructure.execution.local import LocalSnakemakeExecutor
from cygnusx.infrastructure.execution.registry import get_executor, register_executor

__all__ = [
    "BaseExecutor",
    "ExecutionContext",
    "ExecutionResult",
    "BinaryExecutor",
    "LocalSnakemakeExecutor",
    "get_executor",
    "register_executor",
]
