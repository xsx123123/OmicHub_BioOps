"""二进制执行器 — 调用外部 CLI 二进制（如 Rust 写的 EBIDownload）。

与 Snakemake 执行器不同，这里逐行流式读取 stdout 并通过 `on_log` 回调实时推送，
适配 `--log-format json` 的结构化输出：
- 每行先尝试 `json.loads`；命中则取 level/message/progress 字段；
- 解析失败则当纯文本 INFO 日志；
- 命中 progress（0.0~1.0）则经 `on_progress` 回写任务进度。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from cygnusx.infrastructure.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionResult,
)


class BinaryExecutor(BaseExecutor):
    """外部二进制执行器。"""

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        if not ctx.binary:
            return ExecutionResult(
                status="failed", returncode=-1, stderr="未配置二进制路径 (binary)"
            )

        cmd: list[str] = [ctx.binary, *ctx.binary_args]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ctx.work_dir or None,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        assert process.stdout is not None
        assert process.stderr is not None

        async def _drain(stream: asyncio.StreamReader, sink: list[str], is_stderr: bool) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\n")
                if not text.strip():
                    continue
                sink.append(text)
                await self._emit(ctx, text, is_stderr=is_stderr)

        # 并发排空 stdout / stderr，实现真正的逐行实时流式
        drain_stdout = asyncio.create_task(_drain(process.stdout, stdout_lines, is_stderr=False))
        drain_stderr = asyncio.create_task(_drain(process.stderr, stderr_lines, is_stderr=True))

        # 以"进程退出"为完成信号，而非管道 EOF：Celery prefork + asyncio subprocess 下
        # 管道可能不正常 EOF，readline 会永久阻塞，导致 execute() 不返回、任务卡 running。
        returncode = await process.wait()

        # 进程退出后给 drain 短暂收尾窗口，flush 管道缓冲的末尾行；超时则 cancel（管道异常兜底）
        try:
            await asyncio.wait_for(asyncio.gather(drain_stdout, drain_stderr), timeout=2.0)
        except TimeoutError:
            drain_stdout.cancel()
            drain_stderr.cancel()
            await asyncio.gather(drain_stdout, drain_stderr, return_exceptions=True)

        return ExecutionResult(
            status="success" if returncode == 0 else "failed",
            returncode=returncode,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
        )

    async def _emit(self, ctx: ExecutionContext, text: str, *, is_stderr: bool) -> None:
        """解析单行输出并经回调推送日志 / 进度。"""
        level, message, progress = self._parse_line(text)

        if is_stderr and level == "info":
            level = "warning"

        if ctx.on_log is not None:
            await ctx.on_log(level, message, source="binary")

        if progress is not None and ctx.on_progress is not None:
            with contextlib.suppress(Exception):
                await ctx.on_progress(max(0.0, min(1.0, float(progress))))  # 回写失败不影响执行

    @staticmethod
    def _parse_line(text: str) -> tuple[str, str, float | None]:
        """尝试把一行解析为 JSON（{level,message,progress}），失败则当纯文本。"""
        try:
            obj: Any = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return "info", text, None

        if not isinstance(obj, dict):
            return "info", text, None

        level = str(obj.get("level") or "info").lower()
        message = str(obj.get("message") or text)
        progress_raw = obj.get("progress")
        if progress_raw is None:
            progress_raw = obj.get("percent")
        progress: float | None = None
        if progress_raw is not None:
            try:
                progress = float(progress_raw)
                # 兼容 0~100 的百分比写法
                if progress > 1.0:
                    progress = progress / 100.0
            except (TypeError, ValueError):
                progress = None
        return level, message, progress
