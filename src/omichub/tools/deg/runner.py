"""DEG 差异表达分析 R 容器执行器 —— 拼接并运行 `docker run` 调用 DEG 镜像。

镜像由 `make docker-build-deg`（deploy/docker/Dockerfile.deg）构建，脚本烧录在
/opt/deg/run_deseq2.r 与 /opt/deg/run_edger.r；契约见 tool_configs/deg/README.md。
本模块只负责：
- 按 settings/配置拼接 docker run 命令（网络 / 挂载 / 资源 / 超时）；
- asyncio.create_subprocess_exec 执行，事件循环不阻塞；
- 捕获 stdout / stderr，超时则 kill 容器进程。

路径约定：宿主 /data/omichub 与容器内 /data/omichub 同路径挂载，故 input/output
直接用宿主绝对路径即可，容器内所见一致。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from omichub.core.config import get_settings
from omichub.core.telemetry import get_tracer

logger = logging.getLogger(__name__)

# 引擎 → 镜像内脚本路径
SCRIPT_PATHS = {
    "deseq2": "/opt/deg/run_deseq2.r",
    "edger": "/opt/deg/run_edger.r",
}


@dataclass
class DegRunResult:
    """容器执行结果。"""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class DegRunParams:
    """单次 DEG 分析的容器入参（宿主绝对路径 == 容器内路径）。"""

    engine: str                    # deseq2 | edger
    counts_path: str
    metadata_path: str
    pairs_path: str
    output_dir: str
    lfc: float = 1.0
    pval: float = 0.05
    bcv: float = 0.4               # 仅 edger 使用
    annotation_path: str | None = None


class DegDockerRunner:
    """DEG R 分析容器执行器。"""

    def __init__(self) -> None:
        self._settings = get_settings()

    def build_command(self, params: DegRunParams, container_name: str) -> list[str]:
        """构造 `docker run` 命令行参数列表。"""
        from omichub.tools.deg.config import config_manager

        s = self._settings
        execution = config_manager.get_config().execution
        image = s.deg_docker_image or execution.docker_image
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            s.deg_docker_network,
            "-v",
            f"{s.deg_data_mount}:/data/omichub",
            "--memory",
            execution.memory,
            "--cpus",
            str(execution.cpus),
            image,
            "Rscript",
            SCRIPT_PATHS[params.engine],
            "-c",
            params.counts_path,
            "-m",
            params.metadata_path,
            "-p",
            params.pairs_path,
            "-o",
            params.output_dir,
            f"--lfc={params.lfc}",
            f"--pval={params.pval}",
        ]
        if params.annotation_path:
            command.extend(["-a", params.annotation_path])
        if params.engine == "edger":
            command.append(f"--bcv={params.bcv}")
        return command

    async def run(self, params: DegRunParams, container_name: str) -> DegRunResult:
        """执行容器，返回 stdout/stderr/returncode；超时 kill。

        docker run --rm 退出后容器自动清理；kill 主进程会连带终止容器。
        """
        from omichub.tools.deg.config import config_manager

        cmd = self.build_command(params, container_name)
        logger.info("deg docker run: %s", " ".join(cmd))

        tracer = get_tracer("omichub.toolbox")
        with tracer.start_as_current_span(
            "toolbox.runner",
            attributes={"toolbox.runner": "deg", "toolbox.command": " ".join(cmd)[:1000]},
        ) as span:
            start = time.perf_counter()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                timeout = float(
                    self._settings.deg_exec_timeout
                    or config_manager.get_config().execution.timeout
                )
                try:
                    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(proc.communicate(), timeout=10)
                    span.set_attribute("toolbox.returncode", -1)
                    span.set_attribute("toolbox.timed_out", True)
                    return DegRunResult(
                        returncode=-1,
                        stdout="",
                        stderr=f"DEG 分析执行超时（>{int(timeout)}s）",
                        timed_out=True,
                    )

                returncode = proc.returncode if proc.returncode is not None else -1
                span.set_attribute("toolbox.returncode", returncode)
                return DegRunResult(
                    returncode=returncode,
                    stdout=stdout_b.decode("utf-8", errors="replace"),
                    stderr=stderr_b.decode("utf-8", errors="replace"),
                )
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("toolbox.duration_ms", round(duration_ms, 2))
                logger.info("deg runner finished in %.2f ms", duration_ms)
