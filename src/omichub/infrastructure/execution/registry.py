"""执行器注册表 — 按引擎名分发执行器实例。"""

from __future__ import annotations

from omichub.infrastructure.execution.base import BaseExecutor
from omichub.infrastructure.execution.binary import BinaryExecutor
from omichub.infrastructure.execution.local import LocalSnakemakeExecutor

# 引擎名 -> 执行器类（懒实例化由调用方决定，这里保持无状态）
_EXECUTORS: dict[str, type[BaseExecutor]] = {
    "snakemake": LocalSnakemakeExecutor,
    "binary": BinaryExecutor,
}


def get_executor(engine: str) -> BaseExecutor:
    """按引擎名获取执行器实例。

    未知引擎回退到 snakemake（保持与既有行为一致）。
    """
    cls = _EXECUTORS.get(engine, LocalSnakemakeExecutor)
    return cls()


def register_executor(engine: str, cls: type[BaseExecutor]) -> None:
    """注册/覆盖一个引擎的执行器（便于扩展 nextflow 等）。"""
    _EXECUTORS[engine] = cls
