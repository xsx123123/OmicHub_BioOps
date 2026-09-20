"""本地执行器 - Snakemake subprocess"""

import asyncio
import os
import re
import shutil
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionResult,
)

# 容器内通过 docker-compose.worker.yml 挂载到宿主机 /data/cygnusx/logs/snakemake
SNAKEMAKE_LOG_ROOT = Path(os.getenv("CYGNUSX_SNAKEMAKE_LOG_DIR", "/logs/snakemake"))


def _parse_version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _write_snakemake_logs(
    work_dir: str,
    stdout: bytes,
    stderr: bytes,
) -> Path | None:
    """将 Snakemake 的 stdout/stderr 写入统一日志目录。

    目录结构：/logs/snakemake/{project_name}/{timestamp}/
      - stdout.log
      - stderr.log

    返回写入的日志目录；写入失败时返回 None，不影响主流程。
    """
    try:
        project_name = Path(work_dir).name if work_dir else "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = SNAKEMAKE_LOG_ROOT / project_name / timestamp
        log_dir.mkdir(parents=True, exist_ok=True)

        (log_dir / "stdout.log").write_bytes(stdout)
        (log_dir / "stderr.log").write_bytes(stderr)
        return log_dir
    except OSError:
        return None


class LocalSnakemakeExecutor(BaseExecutor):
    """本地 Snakemake 执行器

    通过 subprocess 调用 Snakemake CLI，直接在 Worker 所在服务器执行。
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _ensure_monitor_logger_plugin(self) -> None:
        if not self.settings.workflow_monitor_enabled:
            return
        if self.settings.snakemake_monitor_logger not in {"rich_loguru", "rich-loguru"}:
            return

        package_name = "snakemake-logger-plugin-rich-loguru"
        minimum = self.settings.snakemake_monitor_plugin_min_version
        try:
            installed = version(package_name)
        except PackageNotFoundError as exc:
            raise RuntimeError(
                f"Snakemake logger plugin {package_name}>={minimum} is required but not installed"
            ) from exc

        if _parse_version_tuple(installed) < _parse_version_tuple(minimum):
            raise RuntimeError(
                f"Snakemake logger plugin {package_name}>={minimum} is required, got {installed}"
            )

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """统一执行入口（实现 BaseExecutor 契约）。

        委托给既有的 _execute(...)，保留原缓冲行为，不改 Snakemake 可观测日志。
        """
        if ctx.snakefile is None:
            return ExecutionResult(
                status="failed", returncode=-1, stderr="Snakemake 缺少 snakefile"
            )
        result = await self._execute(
            snakefile=ctx.snakefile,
            work_dir=ctx.work_dir,
            cores=ctx.cores,
            config_file=ctx.config_file,
            config_file_param=ctx.config_file_param,
        )
        return ExecutionResult(
            status=result["status"],
            returncode=result["returncode"],
            stdout=result["stdout"],
            stderr=result["stderr"],
        )

    async def _execute(
        self,
        snakefile: str,
        config: dict[str, Any] | None = None,
        cores: int | None = None,
        work_dir: str = "",
        targets: list[str] | None = None,
        config_file: str | None = None,
        config_file_param: str = "analysisyaml",
    ) -> dict[str, Any]:
        """执行 Snakemake 工作流（既有实现，向后兼容）。

        Args:
            snakefile: Snakefile 路径
            config: 需要以 --config key=value 形式传递的配置字典
            cores: CPU 核心数
            work_dir: Snakemake --directory 工作目录
            targets: 目标文件列表
            config_file: 若提供，则以 --config <config_file_param>=<config_file> 形式传递
            config_file_param: 流程接收配置文件的 --config 参数名，默认 analysisyaml
                               （RNAFlow 使用 analysisyaml；其他流程可在 execution 中指定）

        Returns:
            执行结果，包含 status, stdout, stderr, returncode
        """
        self._ensure_monitor_logger_plugin()

        cmd = [
            "snakemake",
            "-s",
            snakefile,
            "--cores",
            str(cores or self.settings.snakemake_cores),
        ]

        if self.settings.snakemake_use_conda:
            cmd.extend(["--use-conda", "--conda-prefix", self.settings.snakemake_conda_prefix])

        if self.settings.workflow_monitor_enabled and self.settings.snakemake_monitor_logger:
            cmd.extend(["--logger", self.settings.snakemake_monitor_logger])

        monitor_config = Path(work_dir) / "monitor_config.yaml" if work_dir else None

        if work_dir:
            cmd.extend(["--directory", work_dir])

        if targets:
            cmd.extend(targets)

        if config_file:
            cmd.extend(["--config", f"{config_file_param}={config_file}"])
            if monitor_config and monitor_config.exists():
                cmd.append(f"monitor_conf={monitor_config}")
        elif config:
            for key, value in config.items():
                cmd.extend(["--config", f"{key}={value}"])
            if monitor_config and monitor_config.exists():
                cmd.extend(["--config", f"monitor_conf={monitor_config}"])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        stdout_str = stdout.decode()
        stderr_str = stderr.decode()
        log_dir = _write_snakemake_logs(work_dir, stdout, stderr)

        return {
            "status": "success" if process.returncode == 0 else "failed",
            "returncode": process.returncode,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "log_dir": str(log_dir) if log_dir else None,
        }

    async def generate_dag(
        self,
        snakefile: str,
        config_file: str = "",
        work_dir: str = "",
        config_file_param: str = "analysisyaml",
    ) -> dict[str, Any]:
        """生成 Snakemake DAG 可视化。

        若系统安装了 graphviz 的 dot，则返回 SVG；否则返回 DOT 文本。
        """
        cmd = [
            "snakemake",
            "-s",
            snakefile,
            "--dag",
            "--cores",
            "1",
        ]

        if self.settings.snakemake_use_conda:
            cmd.extend(["--use-conda", "--conda-prefix", self.settings.snakemake_conda_prefix])

        if work_dir:
            cmd.extend(["--directory", work_dir])

        if config_file:
            cmd.extend(["--config", f"{config_file_param}={config_file}"])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        dot_text, stderr = await process.communicate()
        dot_text_str = dot_text.decode()

        if process.returncode != 0:
            return {
                "status": "failed",
                "returncode": process.returncode,
                "error": stderr.decode(),
            }

        if shutil.which("dot"):
            dot_proc = await asyncio.create_subprocess_exec(
                "dot",
                "-Tsvg",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            svg_bytes, dot_err = await dot_proc.communicate(input=dot_text)
            if dot_proc.returncode == 0:
                return {
                    "status": "success",
                    "format": "svg",
                    "content": svg_bytes.decode(),
                }
            return {
                "status": "success",
                "format": "dot",
                "content": dot_text_str,
                "warning": f"dot 渲染失败: {dot_err.decode()}",
            }

        return {
            "status": "success",
            "format": "dot",
            "content": dot_text_str,
        }
