"""执行器抽象基类 — 统一 Snakemake / 二进制 / 未来引擎的执行契约。

设计要点：
- `ExecutionContext` 把执行所需的一切打包：引擎、工作目录、Snakemake 参数或
  二进制 + 参数，以及 `on_log` / `on_progress` 回调。
- 回调把"日志如何持久化 + 如何 Pub/Sub"交给调用方（Celery 任务），执行器本身
  不碰 DB / Redis，保持纯净可测试。
- `ExecutionResult` 是统一的执行结果，status="success"|"failed"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class ExecutionContext:
    """执行上下文 — 由调用方（Celery 任务）构造。"""

    engine: str
    work_dir: str = ""
    # ---- Snakemake 专用 ----
    snakefile: str | None = None
    config_file: str | None = None
    config_file_param: str = "analysisyaml"
    cores: int = 4
    # ---- 二进制专用 ----
    binary: str | None = None
    binary_args: list[str] = field(default_factory=list)
    # ---- 通用回调（可选）----
    on_log: Callable[[str, str, str], Awaitable[None]] | None = None
    on_progress: Callable[[float], Awaitable[None]] | None = None


@dataclass
class ExecutionResult:
    """统一执行结果。"""

    status: str  # "success" | "failed"
    returncode: int
    stdout: str = ""
    stderr: str = ""


class BaseExecutor(ABC):
    """执行器抽象基类。"""

    @abstractmethod
    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """按上下文执行，返回统一结果。"""
        raise NotImplementedError
